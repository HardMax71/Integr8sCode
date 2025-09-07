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
    """
    Safely get client IP address from request.
    Handles both normal connections and proxy forwarded requests.
    """
    # Check for proxy headers first (in order of preference)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip

    # Fall back to direct client connection
    if request.client:
        return request.client.host

    # Should rarely happen, but handle the case where client is None
    return "127.0.0.1"
