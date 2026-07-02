from __future__ import annotations
import logging
import socket
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_cache: Dict[str, Tuple[List[str], float]] = {}
_TTL = 300


def resolve(hostname: str, ttl: int = _TTL) -> Optional[List[str]]:
    now = time.time()
    entry = _cache.get(hostname)
    if entry and (now - entry[1]) < ttl:
        return entry[0]
    try:
        addrs = socket.getaddrinfo(hostname, 80)
        ips = list(set(a[4][0] for a in addrs))
        _cache[hostname] = (ips, now)
        logger.debug(f"DNS resuelto: {hostname} -> {ips}")
        return ips
    except socket.gaierror as e:
        logger.warning(f"DNS falló para {hostname}: {e}")
        _cache[hostname] = ([], now)
        return None


def check_connectivity(hostname: str, port: int = 80, timeout: float = 5.0) -> bool:
    ips = resolve(hostname)
    if not ips:
        return False
    for ip in ips[:2]:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            continue
    return False


def clear():
    _cache.clear()
