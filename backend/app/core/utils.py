from enum import StrEnum

from fastapi import Request


class StringEnum(StrEnum):
    """
    A StrEnum subclass that behaves like a plain string in all representations.

    This fixes the issue where StrEnum.__repr__ returns the enum member representation
    (e.g., '<MyEnum.VALUE: 'value'>') instead of just the string value.

    Usage:
        class MyEnum(StringEnum):
            VALUE1 = "value1"
            VALUE2 = "value2"

        # Now repr() returns just "value1" instead of "<MyEnum.VALUE1: 'value1'>"
    """

    def __repr__(self) -> str:
        """Return the string value directly, not the enum member representation."""
        return self.value

    def __str__(self) -> str:
        """Return the string value."""
        return self.value

    def __format__(self, format_spec: str) -> str:
        """Format as a plain string."""
        return self.value.__format__(format_spec)


def get_client_ip(request: Request) -> str:
    """Get client IP address from request.

    Uses the direct connection IP as the authoritative source.
    X-Forwarded-For is only trusted when the direct connection comes from a
    known local/proxy address, preventing attackers from spoofing their IP to
    bypass rate limiting.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"

    if _is_trusted_proxy(direct_ip):
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

    return direct_ip


def _is_trusted_proxy(ip: str) -> bool:
    """Check if an IP belongs to a trusted proxy (loopback or Docker-internal ranges)."""
    return (
        ip.startswith("127.")
        or ip == "::1"
        or ip.startswith("10.")
        or ip.startswith("172.")
        or ip.startswith("192.168.")
    )
