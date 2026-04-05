"""Package-level smoke tests."""

from importlib.metadata import version as package_version

from cellin import __version__


def test_package_version_is_defined() -> None:
    assert __version__ == package_version("cellin")
