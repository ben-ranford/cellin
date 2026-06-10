"""Single-source package metadata."""

from __future__ import annotations

import os

__all__ = ["__channel__", "__version__"]

__channel__ = os.getenv("CELLIN_RELEASE_CHANNEL", "release")
__version__ = "0.4.0"  # x-release-please-version
