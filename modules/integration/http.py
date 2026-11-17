"""The only outbound HTTP path (section 4.4, rule 5).

Controls: destination allow-list, refusal of internal addresses (T-08), per-host pacing, bounded
retries, response size cap. Responses are untrusted; connectors validate them before returning.
"""

import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit

import httpx

from core.config import get_settings
from core.errors import ProviderError
from modules.logging import Severity, log

_transport: httpx.BaseTransport | None = None
_last_call: dict[str, float] = {}
_lock = threading.Lock()
MIN_INTERVAL = {"data.sec.gov": 0.25, "www.sec.gov": 0.25}  # SEC allows 10 requests per second
DEFAULT_INTERVAL = 0.2
USER_AGENT = "AUREX/0.1 (financial research terminal)"


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Replace the network with a recorded transport (tests). No live calls in CI."""
    global _transport
    _transport = transport


def _check_destination(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ProviderError("Outbound calls must use https", code="destination_refused")
    if host not in get_settings().outbound_allow_hosts:
        log("integration", "outbound.refused", Severity.SECURITY, host=host)
        raise ProviderError("Destination is not on the allow-list", code="destination_refused", details={"host": host})
    if _transport is None:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ProviderError("Destination could not be resolved", details={"host": host}) from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                log("integration", "outbound.internal_address", Severity.SECURITY, host=host)
                raise ProviderError("Destination resolves to an internal address", code="destination_refused")
    return host


def _pace(host: str) -> None:
    interval = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    with _lock:
        wait = _last_call.get(host, 0.0) + interval - time.monotonic()
        if wait > 0 and _transport is None:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def fetch(
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    max_bytes: int = 40 * 1024 * 1024,
    attempts: int = 4,
) -> bytes:
    host = _check_destination(url)
    merged = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", **(headers or {})}
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        _pace(host)
        try:
            with httpx.Client(transport=_transport, timeout=timeout, follow_redirects=False) as client:
                with client.stream("GET", url, params=params, headers=merged) as response:
                    if response.status_code in (429, 500, 502, 503, 504):
                        raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
                    if response.status_code == 404:
                        raise ProviderError(
                            "Provider has no such resource", code="provider_not_found", details={"host": host}
                        )
                    if response.status_code >= 400:
                        raise ProviderError(
                            "Provider rejected the request",
                            code="provider_rejected",
                            details={"host": host, "status": response.status_code},
                        )
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ProviderError(
                                "Provider response is too large",
                                code="provider_oversized",
                                details={"host": host, "max_bytes": max_bytes},
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if attempt < attempts and _transport is None:
                time.sleep(min(2.0**attempt, 20.0))
    log("integration", "outbound.failed", Severity.WARN, host=host, attempts=attempts, error=type(last).__name__)
    raise ProviderError("Provider is unavailable", code="provider_unavailable", details={"host": host})
