from __future__ import annotations

from ipaddress import ip_address
import os
import re
import socket
import subprocess


MAC_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def normalize_mac(value: str | None) -> str | None:
    """Normalizza un MAC unicast valido senza accettare valori dichiarati dal client."""
    candidate = (value or "").strip()
    if not MAC_PATTERN.fullmatch(candidate):
        return None
    octets = [int(part, 16) for part in candidate.replace("-", ":").split(":")]
    if octets == [0] * 6 or octets == [255] * 6 or octets[0] & 1:
        return None
    return ":".join(f"{octet:02X}" for octet in octets)


def get_remote_mac(remote_ip: str) -> str | None:
    """Legge il MAC dalla tabella neighbor del server; non usa header HTTP."""
    try:
        parsed_ip = ip_address(remote_ip)
    except ValueError:
        return None
    if parsed_ip.version != 4 or parsed_ip.is_loopback:
        return None

    command = (
        ["arp", "-a", str(parsed_ip)]
        if os.name == "nt"
        else ["ip", "neighbor", "show", str(parsed_ip)]
    )
    run_options = {
        "capture_output": True,
        "text": True,
        "timeout": 1,
        "check": False,
    }
    if os.name == "nt":
        run_options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(command, **run_options)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    expected_ip = str(parsed_ip)
    for line in result.stdout.splitlines():
        tokens = line.replace("(", " ").replace(")", " ").split()
        if expected_ip not in tokens:
            continue
        for token in tokens:
            mac_address = normalize_mac(token)
            if mac_address:
                return mac_address
    return None


def get_remote_ip(request) -> str:
    """Restituisce l'IP del peer senza fidarsi di header inoltrati dal client."""
    raw_address = request.META.get("REMOTE_ADDR", "127.0.0.1").split("%", 1)[0]
    try:
        return str(ip_address(raw_address))
    except ValueError:
        return raw_address


def get_lan_ipv4_addresses() -> list[str]:
    candidates: set[str] = set()
    preferred_address = None
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
            preferred_address = probe.getsockname()[0]
            candidates.add(preferred_address)
    except OSError:
        pass

    addresses = []
    for candidate in candidates:
        try:
            parsed = ip_address(candidate)
        except ValueError:
            continue
        if (
            parsed.version == 4
            and not parsed.is_loopback
            and not parsed.is_link_local
            and not parsed.is_multicast
            and not parsed.is_unspecified
        ):
            addresses.append(str(parsed))
    addresses = sorted(set(addresses), key=lambda value: tuple(int(part) for part in value.split(".")))
    if preferred_address in addresses:
        addresses.remove(preferred_address)
        addresses.insert(0, preferred_address)
    return addresses


def get_server_connection_info(request) -> dict:
    """Compone in un solo punto IP, porta e URL mostrati nell'interfaccia."""
    addresses = get_lan_ipv4_addresses()
    port = request.get_port()
    urls = [f"http://{address}:{port}" for address in addresses]
    return {
        "server_addresses": addresses,
        "server_ip": addresses[0] if addresses else None,
        "server_port": port,
        "lan_urls": urls,
        "primary_lan_url": urls[0] if urls else None,
    }
