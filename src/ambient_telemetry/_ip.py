from __future__ import annotations

import ipaddress


def public_ip(value: object) -> str | None:
    """Normalize ``value`` to a public IP address, or ``None``.

    Accepts what proxies and servers actually hand over: ``1.2.3.4``, ``1.2.3.4:5678``,
    ``[2001:db8::1]:443`` and IPv4-mapped IPv6 (``::ffff:1.2.3.4``). Anything that is not a
    valid, globally routable address (private, loopback, link-local, CGNAT, junk) yields
    ``None``, so a load balancer's internal address is never recorded as the user's.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 64:
        return None
    if text.startswith("["):  # [v6]:port
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1:  # v4:port (a bare v6 has several colons)
        text = text.split(":", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return str(addr) if addr.is_global else None
