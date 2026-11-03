from __future__ import annotations

import ipaddress

# IPv6 global unicast is 2000::/3. Spelled out (not `is_global`, which differs between Python
# versions and accepts multicast, NAT64 and unallocated space) minus the ranges that are never
# a client: IETF protocol/Teredo, documentation, and 6to4. The TypeScript library uses the
# same rule, so one user's address is the same string in both.
_V6_UNICAST = ipaddress.IPv6Network("2000::/3")
_V6_EXCLUDED = tuple(
    ipaddress.IPv6Network(n)
    for n in ("2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20")
)


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
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        else:
            ok = addr in _V6_UNICAST and not any(addr in n for n in _V6_EXCLUDED)
            return str(addr) if ok else None
    return str(addr) if addr.is_global and not addr.is_multicast else None
