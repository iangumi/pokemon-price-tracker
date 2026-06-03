"""HTTP fetching — infrastructure concern."""

from __future__ import annotations

import gzip
import importlib.util
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Accept-Encoding": "gzip",
}


CLOUDFLARE_BYPASS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_text(
    url: str,
    timeout: int = 30,
    retries: int = 2,
    headers: dict | None = None,
    backend: str = "auto",
) -> str:
    selected_backend = resolve_fetch_backend(url, backend)
    if selected_backend == "scrapling":
        try:
            return _fetch_text_scrapling(url, timeout=timeout, dynamic=False)
        except ImportError:
            if backend != "auto":
                raise RuntimeError('Scrapling is not installed. Install with: pip install "scrapling[fetchers]"')
        except RuntimeError:
            if backend != "auto":
                raise
    if selected_backend == "scrapling_dynamic":
        try:
            return _fetch_text_scrapling(url, timeout=timeout, dynamic=True)
        except ImportError:
            if backend != "auto":
                raise RuntimeError('Scrapling is not installed. Install with: pip install "scrapling[fetchers]"')
        except RuntimeError:
            if backend != "auto":
                raise
    return _fetch_text_stdlib(url, timeout=timeout, retries=retries, headers=headers)


def select_fetch_backend(url: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    host = urlparse(url).netloc.lower()
    if "ebay." in host:
        return "scrapling"
    return "stdlib"


def resolve_fetch_backend(url: str, requested: str = "auto") -> str:
    selected = select_fetch_backend(url, requested)
    if requested == "auto" and selected.startswith("scrapling") and not is_scrapling_available():
        return "stdlib"
    return selected


def is_scrapling_available() -> bool:
    return importlib.util.find_spec("scrapling") is not None


def classify_fetch_error(error: Exception | str) -> str:
    text = str(error).lower()
    if "http error 403" in text or "status 403" in text or " forbidden" in text:
        return "http_403"
    if "http error 404" in text or "status 404" in text or " not found" in text:
        return "http_404"
    if "http error 429" in text or "status 429" in text or "too many requests" in text:
        return "http_429"
    if any(marker in text for marker in ("captcha", "cloudflare", "turnstile", "challenge")):
        return "captcha_or_challenge"
    if "scrapling is not installed" in text:
        return "scrapling_unavailable"
    if "urlopen error" in text or "timed out" in text or "timeout" in text:
        return "network_error"
    return "fetch_error"


def _fetch_text_stdlib(url: str, timeout: int = 30, retries: int = 2, headers: dict | None = None) -> str:
    last_error: Exception | None = None
    request_headers = DEFAULT_HEADERS.copy()
    if headers:
        request_headers.update(headers)
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def _fetch_text_scrapling(url: str, timeout: int = 30, dynamic: bool = False) -> str:
    try:
        if dynamic:
            from scrapling.fetchers import DynamicFetcher
        else:
            from scrapling.fetchers import FetcherSession
    except ImportError as exc:
        raise exc

    try:
        if dynamic:
            page = DynamicFetcher.fetch(
                url,
                headless=True,
                network_idle=True,
                timeout=timeout * 1000,
            )
        else:
            with FetcherSession(impersonate="chrome") as session:
                page = session.get(url, stealthy_headers=True, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"Could not fetch {url} with Scrapling: {exc}") from exc

    return _scrapling_page_to_text(page)


def _scrapling_page_to_text(page: object) -> str:
    for attr in ("html_content", "content", "body", "text"):
        value = getattr(page, attr, None)
        if callable(value):
            value = value()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value:
            return value
    return str(page)
