"""Vulture whitelist — framework-required code that appears unused at the AST level.

Structlog processors must accept (logger, method_name, event_dict) by convention,
even when `method_name` is unused in the body.
"""

method_name  # unused variable (app/core/logging.py:36)
method_name  # unused variable (app/core/logging.py:53)
