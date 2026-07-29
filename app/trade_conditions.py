from __future__ import annotations

from typing import Any

# Alpaca documents minute-bar price-update rules by consolidated tape. The exact
# signal and stop/target triggers use only trades whose full condition set can
# update minute-bar prices. Unknown conditions are rejected conservatively.
_ALLOWED_MINUTE_PRICE_CONDITIONS: dict[str, set[str]] = {
    "A": {"", "E", "F", "K", "L", "O", "X", "5", "6"},
    "B": {"", "E", "F", "K", "L", "O", "X", "5", "6"},
    "C": {"@", "A", "B", "D", "F", "K", "L", "O", "X", "Y", "5", "6"},
}


def price_updating_trade(row: dict[str, Any]) -> bool:
    tape = str(row.get("z") or row.get("tape") or "").upper()
    conditions = row.get("c", row.get("conditions")) or []
    if isinstance(conditions, str):
        conditions = [conditions]
    if not conditions:
        # Conditionless trades are regular sales on tapes A/B. Some historical
        # payloads omit tape; accepting conditionless rows matches bar construction.
        return tape in {"", "A", "B"}
    allowed = _ALLOWED_MINUTE_PRICE_CONDITIONS.get(tape)
    if allowed is None:
        return False
    return all(str(condition) in allowed for condition in conditions)
