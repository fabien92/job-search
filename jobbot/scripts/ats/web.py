"""Guarded HTTP GET for the V3 scripts (connectors, detection, contact-source checks).

Every request, redirects included:
  1. the host must be `allowed` in sites.yaml — otherwise NotAllowed, no request at all
     (the caller records the host as pending, with the page that asked for it);
  2. robots.txt of that host must allow the path for our user agent — otherwise RobotsDenied;
  3. Crawl-delay (or the default delay) is respected between two requests to the same host.
The transport is injectable (`opener`) so tests never open a socket.
"""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import sites

USER_AGENT = "JobBot/1.0 (personal job search; low volume)"
DEFAULT_DELAY = 1.0
MAX_BYTES = 3_000_000
TIMEOUT = 20
REDIRECTS = (301, 302, 303, 307, 308)
ROBOTS_REDIRECTS = 3


class FetchError(RuntimeError):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{reason}: {url}")
        self.url, self.reason = url, reason


class NotAllowed(FetchError):
    def __init__(self, url: str, host: str):
        super().__init__(url, "host not allowed in sites.yaml")
        self.host = host


class RobotsDenied(FetchError):
    def __init__(self, url: str):
        super().__init__(url, "disallowed by robots.txt")


def _ssl_context():
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # redirects are followed by Fetcher.get, which re-checks host and robots


def urllib_opener(url: str, headers: dict, timeout: float) -> tuple[int, bytes, dict]:
    """Real transport: one GET, no automatic redirect. -> (status, body, headers)."""
    if os.environ.get("JOBBOT_NO_NETWORK"):
        raise FetchError(url, "network disabled (JOBBOT_NO_NETWORK)")
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_BYTES + 1), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_BYTES + 1) if exc.fp else b"", dict(exc.headers or {})
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(url, f"network error ({type(exc).__name__})") from exc


class Fetcher:
    def __init__(self, whitelist: dict | None = None, opener=None, delay: float = DEFAULT_DELAY, sleep=time.sleep):
        self.whitelist = whitelist if whitelist is not None else sites.load()
        self.opener = opener or urllib_opener
        self.delay = delay
        self.sleep = sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self.requests = 0

    # -------------------------------------------------------------- helpers
    def check_host(self, url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            raise FetchError(url, "only https URLs are fetched")
        if not sites.is_allowed(host, self.whitelist):
            raise NotAllowed(url, host)
        return host

    def _wait(self, host: str, crawl_delay: float | None) -> None:
        gap = max(self.delay, crawl_delay or 0)
        last = self._last.get(host)
        if last is not None:
            remaining = gap - (time.monotonic() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last[host] = time.monotonic()

    def _raw(self, url: str, host: str, accept: str, crawl_delay: float | None = None) -> tuple[int, bytes, dict]:
        self._wait(host, crawl_delay)
        self.requests += 1
        return self.opener(url, {"User-Agent": USER_AGENT, "Accept": accept}, TIMEOUT)

    def robots(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        """None = no usable robots.txt (404 etc.): everything allowed, as the standard says.
        A 401/403 or an error reading it = everything disallowed (conservative).
        A redirect (apex -> www…) is followed, at most ROBOTS_REDIRECTS times, each target through the
        same whitelist check as any request; a redirect that cannot be followed = everything disallowed.
        (An unfollowed 3xx used to be parsed as an empty file, i.e. "everything allowed".)"""
        if host in self._robots:
            return self._robots[host]
        url = f"https://{host}/robots.txt"
        parser = urllib.robotparser.RobotFileParser(url)
        status, body = 503, b""
        try:
            target = url
            for _ in range(ROBOTS_REDIRECTS + 1):
                status, body, headers = self._raw(target, self.check_host(target), "text/plain")
                if status not in REDIRECTS:
                    break
                location = {k.lower(): v for k, v in headers.items()}.get("location")
                if not location:
                    raise FetchError(target, f"HTTP {status} without Location")
                target = urljoin(target, location)
            else:
                raise FetchError(target, "too many redirects")
        except FetchError:  # NotAllowed included: the redirect target is never contacted
            status, body = 503, b""
        if status in (401, 403) or status >= 500:
            parser.disallow_all = True
        elif 400 <= status < 500:
            parser = None
        else:
            parser.parse(body.decode("utf-8", "replace").splitlines())
        self._robots[host] = parser
        return parser

    def allowed_by_robots(self, url: str) -> bool:
        host = self.check_host(url)
        parser = self.robots(host)
        return parser is None or parser.can_fetch(USER_AGENT, url)

    # -------------------------------------------------------------- public
    def get(self, url: str, accept: str = "*/*", max_redirects: int = 3) -> tuple[str, str]:
        """-> (final url, body text). Raises NotAllowed / RobotsDenied / FetchError."""
        for _ in range(max_redirects + 1):
            host = self.check_host(url)
            parser = self.robots(host)
            if parser is not None and not parser.can_fetch(USER_AGENT, url):
                raise RobotsDenied(url)
            delay = parser.crawl_delay(USER_AGENT) if parser is not None else None
            status, body, headers = self._raw(url, host, accept, float(delay) if delay else None)
            if status in REDIRECTS:
                location = {k.lower(): v for k, v in headers.items()}.get("location")
                if not location:
                    raise FetchError(url, f"HTTP {status} without Location")
                url = urljoin(url, location)
                continue
            if status != 200:
                raise FetchError(url, f"HTTP {status}")
            if len(body) > MAX_BYTES:
                raise FetchError(url, "response too large")
            return url, body.decode("utf-8", "replace")
        raise FetchError(url, "too many redirects")
