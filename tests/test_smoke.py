"""Smoke test: verify the package can be imported and exposes its version."""

import marionette


def test_marionette_imports() -> None:
    """The package imports without error."""
    assert marionette is not None


def test_marionette_version() -> None:
    """The package exposes a version string matching pyproject.toml."""
    assert marionette.__version__ == "0.1.0"
