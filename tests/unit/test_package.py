"""Package-level smoke tests."""

from cellin import __version__


def test_package_version_is_defined() -> None:
    assert __version__ == "0.1.0"
