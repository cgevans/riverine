"""Tests to verify alhambra_mixes stub properly re-exports riverine."""

import pytest


def test_import_alhambra_mixes():
    """Test that alhambra_mixes can be imported."""
    import alhambra_mixes
    assert alhambra_mixes is not None


def test_all_exports_available():
    """Test that all major exports from riverine are available in alhambra_mixes."""
    import alhambra_mixes
    
    # Check key classes are available
    assert hasattr(alhambra_mixes, 'Mix')
    assert hasattr(alhambra_mixes, 'Component')
    assert hasattr(alhambra_mixes, 'Strand')
    assert hasattr(alhambra_mixes, 'Experiment')
    assert hasattr(alhambra_mixes, 'WellPos')
    assert hasattr(alhambra_mixes, 'Reference')
    
    # Check actions are available
    assert hasattr(alhambra_mixes, 'FixedVolume')
    assert hasattr(alhambra_mixes, 'FixedConcentration')
    assert hasattr(alhambra_mixes, 'EqualConcentration')
    assert hasattr(alhambra_mixes, 'ToConcentration')
    assert hasattr(alhambra_mixes, 'FillToVolume')
    assert hasattr(alhambra_mixes, 'MultiFixedVolume')
    assert hasattr(alhambra_mixes, 'MultiFixedConcentration')
    
    # Check units are available
    assert hasattr(alhambra_mixes, 'uL')
    assert hasattr(alhambra_mixes, 'uM')
    assert hasattr(alhambra_mixes, 'nM')
    assert hasattr(alhambra_mixes, 'Q_')
    assert hasattr(alhambra_mixes, 'ureg')
    
    # Check functions are available
    assert hasattr(alhambra_mixes, 'load_reference')
    assert hasattr(alhambra_mixes, 'master_mix')
    assert hasattr(alhambra_mixes, 'split_mix')


def test_classes_are_same_as_riverine():
    """Test that classes from alhambra_mixes are the same as riverine."""
    import alhambra_mixes
    import riverine
    
    # Classes should be identical (same object)
    assert alhambra_mixes.Mix is riverine.Mix
    assert alhambra_mixes.Component is riverine.Component
    assert alhambra_mixes.Strand is riverine.Strand
    assert alhambra_mixes.Experiment is riverine.Experiment
    assert alhambra_mixes.FixedVolume is riverine.FixedVolume
    assert alhambra_mixes.FixedConcentration is riverine.FixedConcentration


def test_can_create_component():
    """Test that we can create a Component using alhambra_mixes."""
    from alhambra_mixes import Component, nM, uL
    
    comp = Component(name="test", concentration=100 * nM, volume=10 * uL)
    assert comp.name == "test"
    assert comp.concentration.magnitude == 100
    assert comp.volume.magnitude == 10


def test_can_create_mix():
    """Test that we can create a Mix using alhambra_mixes."""
    from alhambra_mixes import Mix, Component, FixedVolume, nM, uL
    
    comp = Component(name="test", concentration=100 * nM, volume=10 * uL)
    mix = Mix([FixedVolume(comp, 5 * uL)])
    
    assert len(mix.actions) == 1
    assert mix.actions[0].components[0].name == "test"


def test_echo_imports_conditionally():
    """Test that Echo-related imports work if kithairon is available."""
    try:
        from alhambra_mixes import (
            EchoFixedVolume,
            EchoFillToVolume,
            EchoTargetConcentration,
            EchoEqualTargetConcentration,
        )
        # If we get here, kithairon is available
        assert EchoFixedVolume is not None
        assert EchoFillToVolume is not None
        assert EchoTargetConcentration is not None
        assert EchoEqualTargetConcentration is not None
    except ImportError as e:
        # kithairon not available, which is fine
        if "kithairon" not in str(e):
            raise


def test_version_available():
    """Test that __version__ is available."""
    import alhambra_mixes
    assert hasattr(alhambra_mixes, '__version__')
    assert isinstance(alhambra_mixes.__version__, str)


def test_all_attribute_exists():
    """Test that __all__ is properly exported."""
    import alhambra_mixes
    assert hasattr(alhambra_mixes, '__all__')
    assert isinstance(alhambra_mixes.__all__, list)
    assert 'Mix' in alhambra_mixes.__all__
    assert 'Component' in alhambra_mixes.__all__


def test_printing_module_available():
    """Test that the printing submodule is available."""
    import alhambra_mixes
    assert hasattr(alhambra_mixes, 'printing')
    assert hasattr(alhambra_mixes.printing, 'plate')

