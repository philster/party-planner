"""HTTP fetching for the extractors: plain curl by default, curl_cffi when a
site fingerprints the TLS handshake (e.g. Splashthat behind DataDome).

  from httpfetch import fetch, FetchError
"""
import subprocess

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class FetchError(RuntimeError):
    pass


def fetch(url, impersonate=None, timeout=30):
    """Return the page text. With `impersonate` set (e.g. "chrome"), use
    curl_cffi to pass a passive browser-fingerprint check; otherwise plain curl."""
    if impersonate:
        try:
            from curl_cffi import requests as creq
        except ImportError:
            raise FetchError("curl_cffi required for this site "
                             "(pip install curl-cffi)")
        try:
            resp = creq.get(url, impersonate=impersonate, timeout=timeout,
                            allow_redirects=True,
                            headers={"Accept-Language": "en-US,en;q=0.9"})
        except Exception as err:
            raise FetchError("request failed: %s" % err)
        if resp.status_code != 200:
            hint = ""
            if resp.status_code == 403:
                hint = " (blocked — try a newer impersonate target)"
            raise FetchError("HTTP %s%s" % (resp.status_code, hint))
        return resp.text

    proc = subprocess.run(
        ["curl", "-sSL", "--compressed", "--max-time", str(timeout),
         "--retry", "2", "--retry-delay", "1", "-A", UA,
         "-H", "Accept-Language: en-US,en;q=0.9", url],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FetchError(proc.stderr.strip() or "curl failed (exit %d)" % proc.returncode)
    if not proc.stdout.strip():
        raise FetchError("empty response")
    return proc.stdout
