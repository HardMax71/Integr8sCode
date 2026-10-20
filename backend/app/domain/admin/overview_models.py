from dataclasses import dataclass


@dataclass
class DerivedCountsDomain:
    succeeded: int = 0
    failed: int = 0
    timeout: int = 0
    cancelled: int = 0
    terminal_total: int = 0
