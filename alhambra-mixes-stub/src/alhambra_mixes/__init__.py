"""
Compatibility stub for riverine (formerly alhambra-mixes).

This package re-exports all of riverine's public API to maintain
backwards compatibility with code that imports alhambra_mixes.
"""

import sys
import warnings

warnings.warn(
    "The 'alhambra_mixes' package has been renamed to 'riverine'. "
    "Please update your imports to use 'riverine' instead. "
    "This compatibility stub will be removed in a future version. "
    "See https://github.com/cgevans/mixes for more information.",
    FutureWarning,
    stacklevel=2
)

from riverine import *  # noqa: F401, F403
from riverine import __all__  # noqa: F401

import riverine as _riverine

__version__ = _riverine.__version__ if hasattr(_riverine, '__version__') else '0.7.0'


def __getattr__(name):
    """Dynamically import submodules from riverine."""
    import importlib
    try:
        riverine_module = importlib.import_module(f"riverine.{name}")
        sys.modules[f"alhambra_mixes.{name}"] = riverine_module
        return riverine_module
    except ImportError:
        raise AttributeError(f"module 'alhambra_mixes' has no attribute '{name}'")

