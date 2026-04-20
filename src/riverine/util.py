from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import functools

if TYPE_CHECKING:
    from kithairon.picklists import PickList

T = TypeVar("T")

CACHE_HITS = 0
CACHE_MISSES = 0
CACHE_SKIPS = 0

# Largely replaced by concrete type code.
# def _maybesequence(object_or_sequence: Sequence[T] | T) -> list[T]:
#     if isinstance(object_or_sequence, Sequence):
#         return list(object_or_sequence)
#     return [object_or_sequence]


def _none_as_empty_string(v: str | None) -> str:
    return "" if v is None else v


def _get_picklist_class() -> type[PickList]:
    try:
        from kithairon.picklists import PickList  # type: ignore

        return PickList
    except ImportError as err:
        if err.name != "kithairon":
            raise err
        raise ImportError(
            "kithairon is required for Echo support, but it is not installed.",
            name="kithairon",
        )


__all__ = (
    "_none_as_empty_string",
    "_get_picklist_class",
)


_UNSET = object()


def maybe_cache_once(fun):
    """Cache the result of the most recent call whose `_cache_key` is not None.

    Cache identity is compared by equality on `(_cache_key, args, kwargs)`.
    An earlier version keyed by `hash(...)` alone, which returned stale data
    on any hash collision.
    """

    last_key: object = _UNSET
    last_cache_data = None

    def inner(*args, _cache_key=None, **kwargs):
        nonlocal last_key, last_cache_data

        if _cache_key is None:
            global CACHE_SKIPS
            CACHE_SKIPS += 1
            return fun(*args, **kwargs, _cache_key=_cache_key)

        current_key = (_cache_key, args, tuple(sorted(kwargs.items())))
        if last_key is not _UNSET and current_key == last_key:
            global CACHE_HITS
            CACHE_HITS += 1
            return last_cache_data

        global CACHE_MISSES
        CACHE_MISSES += 1
        data = fun(*args, **kwargs, _cache_key=_cache_key)
        last_key = current_key
        last_cache_data = data
        return data

    functools.update_wrapper(inner, fun)

    return inner


def gen_random_hash():
    import random
    import string

    return "".join(random.choices(string.ascii_lowercase + string.digits, k=15))
