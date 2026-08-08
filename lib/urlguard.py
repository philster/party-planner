"""Decide whether a URL may be fetched at all.

`fetch_event` takes whatever the user pasted, and extractors hand back URLs
lifted straight out of page JSON (Partiful's `calendarFile`, for one), so the
fetch layer is reachable with an attacker-chosen target. Without a guard that
means `file:///…/.aws/credentials`, `gopher://127.0.0.1:6379`, or a probe of
`169.254.169.254` — a local-file read and an SSRF primitive handed to anyone
who can get a link in front of the user.

  from urlguard import UrlNotAllowed, resolve, is_allowed_scheme

`resolve` fails closed: the scheme must be http(s), the host must resolve, and
*every* address it resolves to must be publicly routable. Callers pin the
returned address for the actual request, so the name cannot resolve to
something else between the check and the fetch (DNS rebinding).
"""
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("https", "http")


class UrlNotAllowed(ValueError):
    pass


def is_allowed_scheme(url):
    return urlsplit(url or "").scheme.lower() in ALLOWED_SCHEMES


def _classify(raw):
    """An address literal, unwrapped from any IPv4-mapped IPv6 form."""
    ip = ipaddress.ip_address(raw)
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped or ip


def _is_public(ip):
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _literal_readings(host):
    """Every address this host could denote if something treats it as a literal.

    Resolvers disagree here, and the disagreement is exploitable: Python's
    getaddrinfo renders "0177.0.0.1" as the public 177.0.0.1, while libc's
    inet_aton -- and therefore curl -- reads the octal and goes to 127.0.0.1.
    Validating only one reading would wave that straight through, so collect
    them all and require every one to be public."""
    readings = []
    bare = host.strip("[]")
    for parse in (lambda: ipaddress.ip_address(bare),
                  lambda: ipaddress.IPv4Address(socket.inet_ntoa(socket.inet_aton(host)))):
        try:
            readings.append(parse())
        except (ValueError, OSError):
            pass
    return readings


def resolve(url):
    """Return (host, port, [validated ip strings]) or raise UrlNotAllowed."""
    parts = urlsplit(url or "")
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlNotAllowed("scheme %r is not fetchable (allowed: %s)"
                            % (scheme or "none", ", ".join(ALLOWED_SCHEMES)))
    try:
        host, port = parts.hostname, parts.port
    except ValueError as err:          # malformed port
        raise UrlNotAllowed("bad authority: %s" % err)
    if not host:
        raise UrlNotAllowed("no host in URL")
    port = port or (443 if scheme == "https" else 80)

    for reading in _literal_readings(host):
        if not _is_public(reading):
            raise UrlNotAllowed("%s is the non-public address %s" % (host, reading))

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as err:
        raise UrlNotAllowed("could not resolve %r: %s" % (host, err))

    addrs = []
    for info in infos:
        try:
            ip = _classify(info[4][0])
        except ValueError:
            continue
        # Fail closed on the whole name: a DNS answer that mixes a public
        # address with a private one is exactly the SSRF case worth refusing.
        if not _is_public(ip):
            raise UrlNotAllowed("%s resolves to the non-public address %s" % (host, ip))
        addrs.append(str(ip))
    if not addrs:
        raise UrlNotAllowed("%r resolved to no usable address" % host)
    return host, port, addrs


def curl_resolve_arg(host, port, addr):
    """`--resolve` entry pinning host:port to an address we already validated.
    IPv6 literals need brackets."""
    literal = "[%s]" % addr if ":" in addr else addr
    return "%s:%d:%s" % (host, port, literal)
