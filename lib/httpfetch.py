"""HTTP fetching for the extractors: plain curl by default, curl_cffi when a
site fingerprints the TLS handshake (e.g. Splashthat behind DataDome).

  from httpfetch import fetch, FetchError

Redirects are followed here rather than by curl, because every hop has to clear
`urlguard` — otherwise a public URL redirecting to `http://169.254.169.254/`
walks straight past the check on the original URL. curl is invoked with the
validated address pinned via `--resolve`, with a protocol allowlist, a response
size cap, and `--` before the URL.
"""
import os
import re
import subprocess
import tempfile
from urllib.parse import urljoin

import urlguard

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5

_STATUS_RE = re.compile(r"^HTTP/[\d.]+\s+(\d{3})", re.M)
_LOCATION_RE = re.compile(r"^Location:[ \t]*(\S+)", re.I | re.M)


class FetchError(RuntimeError):
    pass


class FetchRefused(FetchError):
    """The URL is one policy forbids, not one that merely failed.

    Kept distinct so callers do not treat it as a transport hiccup and retry by
    some other route -- a fallback that says "fetch this another way" would hand
    back exactly the local file or internal address the guard just refused."""


def _redirect_target(headers):
    """The Location of the final header block, when it is a redirect."""
    blocks = [b for b in re.split(r"\r?\n\r?\n", headers or "")
              if b.strip().upper().startswith("HTTP/")]
    last = blocks[-1] if blocks else (headers or "")
    status = _STATUS_RE.search(last)
    location = _LOCATION_RE.search(last)
    if status and 300 <= int(status.group(1)) < 400 and location:
        return location.group(1)
    return None


def _curl(url, host, port, addr, timeout):
    """One hop. Returns (body, redirect_target); exactly one is meaningful."""
    with tempfile.TemporaryDirectory(prefix="partyplanner-") as tmp:
        headers_path = os.path.join(tmp, "headers")
        proc = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", str(timeout),
             "--retry", "2", "--retry-delay", "1",
             "--proto", "=http,https",          # no file:/gopher:/dict: ever
             "--max-filesize", str(MAX_BYTES),
             "--resolve", urlguard.curl_resolve_arg(host, port, addr),
             "-A", UA, "-H", "Accept-Language: en-US,en;q=0.9",
             "-D", headers_path, "--", url],
            capture_output=True, text=True,
        )
        try:
            headers = open(headers_path, encoding="utf-8", errors="replace").read()
        except OSError:
            headers = ""

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:300] or "curl failed (exit %d)" % proc.returncode
        raise FetchError(detail)
    target = _redirect_target(headers)
    if target:
        return None, target
    if not proc.stdout.strip():
        raise FetchError("empty response")
    return proc.stdout, None


def _cffi(url, impersonate, timeout):
    """One hop through curl_cffi. No address pinning is available here, so the
    per-hop urlguard check is the only protection — acceptable because this
    path is opt-in and only used for Splashthat."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        raise FetchError("curl_cffi required for this site (pip install curl-cffi)")
    try:
        resp = creq.get(url, impersonate=impersonate, timeout=timeout,
                        allow_redirects=False,
                        headers={"Accept-Language": "en-US,en;q=0.9"})
    except Exception as err:
        raise FetchError("request failed: %s" % str(err)[:300])
    if 300 <= resp.status_code < 400:
        target = resp.headers.get("location")
        if target:
            return None, target
    if resp.status_code != 200:
        hint = " (blocked — try a newer impersonate target)" if resp.status_code == 403 else ""
        raise FetchError("HTTP %s%s" % (resp.status_code, hint))
    if len(resp.content or b"") > MAX_BYTES:
        raise FetchError("response exceeds %d bytes" % MAX_BYTES)
    return resp.text, None


def fetch(url, impersonate=None, timeout=30):
    """Return the page text. With `impersonate` set (e.g. "chrome"), use
    curl_cffi to pass a passive browser-fingerprint check; otherwise plain curl.
    Every hop is validated before it is requested."""
    seen = []
    for _ in range(MAX_REDIRECTS + 1):
        try:
            host, port, addrs = urlguard.resolve(url)
        except urlguard.UrlNotAllowed as err:
            raise FetchRefused("refusing to fetch %s: %s" % (url[:200], err))
        seen.append(url)

        if impersonate:
            body, target = _cffi(url, impersonate, timeout)
        else:
            body, target = _curl(url, host, port, addrs[0], timeout)
        if target is None:
            return body

        url = urljoin(url, target)
        if url in seen:
            raise FetchError("redirect loop at %s" % url[:200])
    raise FetchError("more than %d redirects" % MAX_REDIRECTS)
