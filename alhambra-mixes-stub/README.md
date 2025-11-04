# alhambra-mixes

**This package is a compatibility stub. Please use `riverine` instead.**

The `alhambra-mixes` package has been renamed to `riverine`. This stub package
simply re-exports all of `riverine`'s functionality to maintain backwards
compatibility with existing code.

## Migration

To migrate from `alhambra-mixes` to `riverine`, simply replace:

```python
from alhambra_mixes import Mix, Component, ...
```

with:

```python
from riverine import Mix, Component, ...
```

## Installation

```bash
pip install riverine
```

Or if you need the compatibility layer:

```bash
pip install alhambra-mixes
```

Note that installing `alhambra-mixes` will automatically install `riverine` as a dependency.

