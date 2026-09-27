"""One reconcile pass's tab listing — the tabs that answered + the keys HELD (I-68).

Two browsers feed one URL list (Chrome over CDP, Firefox from its session
store). When one of them does not answer, the other must still reconcile —
but the silent one's rows and pool pages must not be read as "closed" (a
failed fetch is a wait, not a removal, I-50). `Listing` carries both halves:
it IS the list of answered tabs, and `held` names the keys of the browser
that said nothing, which the pass treats as present-but-untouchable.
A plain list means "every browser answered" (`held_keys` → empty).
Imports: stdlib only.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Iterable


class Listing(list):
    """Answered tabs (the list itself) + `held`: keys of a browser that did not answer."""

    def __init__(self, tabs: Iterable[Any] = (), held: Iterable[str] = ()):
        super().__init__(tabs)
        self.held: FrozenSet[str] = frozenset(k for k in held if k)


def held_keys(tabs: Any) -> FrozenSet[str]:
    """The held keys of a pass's listing; empty for a plain list or None."""
    return getattr(tabs, "held", None) or frozenset()
