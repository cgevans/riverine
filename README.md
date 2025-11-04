[![Documentation Status](https://readthedocs.org/projects/riverine/badge/?version=latest)](https://riverine.readthedocs.io/en/latest/?badge=latest)
[![Codecov](https://img.shields.io/codecov/c/github/cgevans/riverine)](https://app.codecov.io/gh/cgevans/riverine/)
[![GitHub Workflow
Status](https://img.shields.io/github/actions/workflow/status/cgevans/mixes/python-package.yml?branch=main)](https://github.com/cgevans/mixes/actions/workflows/python-package.yml)
[![PyPI](https://img.shields.io/pypi/v/riverine)](https://pypi.org/project/riverine/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/riverine)](https://pypi.org/project/riverine/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.6861213.svg)](https://doi.org/10.5281/zenodo.6861213)


For DNA 28, our [poster as a Jupyter notebook is available here](https://costi.eu/poster-notebook.zip).  [Our documentation][docsstable] is in the process of being written ([latest git documentation is here][docslatest]); we also have [a tutorial notebook][tutorial] (WIP).


Riverine is a Python library to systematically, efficiently, and safely
design recipes for mixes of many components, intended primarily for DNA
computation experiments.  The library recursively tracks individual components
through layers of intermediate mixes, performs checks to ensure those layers of
mixes are possible, and allows verification that final samples will contain the
correct components at the correct concentrations. Incorporating reference
information from files such as DNA synthesis order details, the library
generates recipes for straightforward pipetting, even in mixes with many
components at different concentrations spread across several plates.

[alhambra]: https://github.com/DNA-and-Natural-Algorithms-Group/alhambra
[docsstable]: https://riverine.readthedocs.io/en/stable
[docslatest]: https://riverine.readthedocs.io/en/latest
[tutorial]: https://github.com/cgevans/mixes/blob/main/tutorial.ipynb

# Changelog

## v0.7.0

- Renames the package from `alhambra-mixes` to `riverine`.
- Replaces `Mix.buffer_name` and `Mix.fixed_total_volume` with a more flexible `FillToVolume` action, like the existing `EchoFillToVolume`.  The existing keywords should remain functional for backwards compatibility: they now add and modify a `FillToVolume` action as needed (or modify an `EchoFillToVolume` action if it already exists).
- Deprecates Python 3.9 support.
- Several bug fixes.

## v0.6.1

- Adds `html_with_borders_tablefmt` again (and import `printing`).

## v0.6.0

- ECHO liquid handler support now included by default. Uses [kithairon](https://github.com/cgevans/kithairon), which
  does require Python ≥ 3.10.

## v0.5.0

An interim version release while larger changes are being made, so that users can make use of several important new features, and the pypi-available version fits well with the latest documentation.

- Adds an `Experiment` class that can hold mixes and components, and keep track of volumes, etc.
- Adds volume/consumption tracking.
- Adds master/split mix functions.
- Fixes numerous minor bugs.