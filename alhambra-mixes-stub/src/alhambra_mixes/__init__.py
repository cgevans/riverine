"""
Compatibility stub for riverine (formerly alhambra-mixes).

This package re-exports all of riverine's public API to maintain
backwards compatibility with code that imports alhambra_mixes.
"""

from riverine import *  # noqa: F401, F403
from riverine import __all__  # noqa: F401

import riverine as _riverine

__version__ = _riverine.__version__ if hasattr(_riverine, '__version__') else '0.6.2a1'

