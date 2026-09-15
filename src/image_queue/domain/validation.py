"""Shared strict boundary validation; errors deliberately omit input values."""

from collections.abc import Mapping


class ContractError(ValueError):
    """Actionable contract failure safe to show without echoing private input."""


class PersistenceFault(ContractError):
    """Write or readback was not acknowledged; caller must reopen for recovery."""


def require_integer(value: object, bounds: tuple[int, int], field: str) -> int:
    """Booleans and fractional values are not integer settings."""
    if type(value) is not int:
        raise ContractError(f"{field}: expected an integer")
    if not bounds[0] <= value <= bounds[1]:
        raise ContractError(f"{field}: outside supported range {bounds}")
    return value


def require_boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ContractError(f"{field}: expected a boolean")
    return value


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field}: expected text")
    return value


def require_fields(value: object, names: set[str], field: str) -> Mapping[str, object]:
    """Reject missing/unknown fields rather than silently discarding saved settings."""
    if not isinstance(value, dict) or set(value) != names:
        raise ContractError(f"{field}: missing or unsupported fields")
    return value
