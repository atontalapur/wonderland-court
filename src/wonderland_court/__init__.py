"""Wonderland Court: put your AI agent on trial."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wonderland-court")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"
