"""ODIN — Open Dinner Invitation Notifier."""

import sys


def main() -> None:
    """Console script entry point: `odib <command>`."""
    from odib.cli import main as cli_main

    sys.exit(cli_main())
