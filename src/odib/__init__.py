"""ODIN — Open Dinner Invitation Notifier."""

import sys
from importlib.metadata import PackageNotFoundError, version

try:
    # Set at build time from the git tag (hatch-vcs), see pyproject.toml.
    __version__ = version("odib")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled tree
    __version__ = "0.0.0+unknown"


def main() -> None:
    """Console script entry point: `odib <command>`."""
    from odib.cli import main as cli_main

    sys.exit(cli_main())
