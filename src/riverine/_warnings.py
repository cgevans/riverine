"""Deprecation warning support for riverine."""

from __future__ import annotations

import warnings


class RiverineDeprecationWarning(FutureWarning):
    """A riverine API scheduled for removal.

    Subclasses :class:`FutureWarning` (rather than :class:`DeprecationWarning`)
    so that it is shown to users by default, including in notebooks and scripts,
    while remaining filterable by category.
    """


def _warn_deprecated(msg: str, *, stacklevel: int = 2) -> None:
    """Emit a :class:`RiverineDeprecationWarning`."""
    warnings.warn(msg, RiverineDeprecationWarning, stacklevel=stacklevel + 1)
