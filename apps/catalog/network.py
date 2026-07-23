from __future__ import annotations

from ipaddress import ip_address
import socket


def get_lan_ipv4_addresses() -> list[str]:
    candidates: set[str] = set()
    try:
        candidates.update(
            result[4][0]
            for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        )
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            candidates.add(probe.getsockname()[0])
    except OSError:
        pass

    addresses = []
    for candidate in candidates:
        try:
            parsed = ip_address(candidate)
        except ValueError:
            continue
        if parsed.version == 4 and parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
            addresses.append(str(parsed))
    return sorted(set(addresses), key=lambda value: tuple(int(part) for part in value.split(".")))
