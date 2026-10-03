"""The `odin` command: run the bot, set it up, list its groups, or check the config."""

import argparse
import asyncio
import logging
import os
import signal
import sqlite3
import sys
from collections.abc import Mapping, Sequence

import httpx

import odin
from odin.app import SETUP_HINT, Source, resolve_account, serve, upcoming_actions
from odin.clock import Clock, SystemClock
from odin.config import ConfigError, Settings, load_settings, load_signal_env
from odin.setup import REDO_STEPS, SetupOptions, run_setup, setup_status
from odin.signal import RestSignalClient, SignalApiError
from odin.store import Store
from odin.terminal import ConsoleTerminal, Terminal

logger = logging.getLogger("odin")

DEFAULT_LOG_LEVEL = "INFO"


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    terminal: Terminal | None = None,
) -> int:
    """Entry point; returns the exit code. Defaults: `sys.argv`, the process env, the real clock,
    the console."""
    environ = os.environ if environ is None else environ
    clock = clock or SystemClock()
    terminal = terminal or ConsoleTerminal()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "setup" and args.status and (args.pin or args.redo):
        parser.error("setup --status cannot be combined with other options")
    try:
        _setup_logging(environ)
        match args.command:
            case "run":
                asyncio.run(_run(load_settings(environ), clock))
            case "setup":
                # The wizard talks to the operator; per-request HTTP logs would drown that.
                logging.getLogger("httpx").setLevel(logging.WARNING)
                return asyncio.run(_setup(load_settings(environ), clock, terminal, args))
            case "list-groups":
                asyncio.run(_list_groups(environ))
            case "check-config":
                _check_config(load_settings(environ), clock)
    except ConfigError as e:
        print(f"odin: configuration error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped. Run `odin setup` again to continue.", file=sys.stderr)
        return 130
    except (httpx.HTTPError, sqlite3.Error, SignalApiError) as e:
        print(f"odin: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odin",
        description="Odin 🍽️ — a Signal bot for the weekly open Sunday dinner.",
        epilog="Configured by env vars: SIGNAL_NUMBER, SIGNAL_API_URL, ODIN_CONFIG, ODIN_DB, "
        "ODIN_LOG_LEVEL. The group IDs are stored in the database by odin setup; "
        "FLAT_GROUP_ID and DINNER_GROUP_ID optionally override them.",
    )
    parser.add_argument("--version", action="version", version=odin.__version__)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser(
        "run",
        help="run the bot until SIGTERM or SIGINT; waits while ODIN is not set up",
    )
    setup = commands.add_parser(
        "setup",
        help="interactive setup: register the number, set PIN and profile, choose the groups; "
        "resumes where it stopped",
    )
    setup.add_argument(
        "--status",
        action="store_true",
        help="only show which steps are done, change nothing; exit code 0 when fully set up",
    )
    setup.add_argument(
        "--pin",
        action="store_true",
        help="enter an own PIN instead of a generated one; also sets a new PIN if one is set",
    )
    setup.add_argument(
        "--redo",
        action="append",
        choices=REDO_STEPS,
        default=[],
        metavar="STEP",
        help=f"repeat a finished step ({', '.join(REDO_STEPS)}); can be given several times",
    )
    commands.add_parser(
        "list-groups",
        help="print the Signal groups the bot is in, with their IDs (for debugging, or for "
        "the FLAT_GROUP_ID / DINNER_GROUP_ID overrides); "
        "needs only SIGNAL_NUMBER and SIGNAL_API_URL",
    )
    commands.add_parser(
        "check-config",
        help="validate the config file and env vars and print the next scheduled actions",
    )
    return parser


def _setup_logging(environ: Mapping[str, str]) -> None:
    level = environ.get("ODIN_LOG_LEVEL", "").strip().upper() or DEFAULT_LOG_LEVEL
    if level not in logging.getLevelNamesMapping():
        raise ConfigError(
            f"ODIN_LOG_LEVEL must be a log level (DEBUG, INFO, WARNING, ERROR), got {level!r}"
        )
    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


async def _run(settings: Settings, clock: Clock) -> None:
    env = settings.env
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    client = RestSignalClient(env.signal_api_url, env.signal_number)
    try:
        with Store(env.db_path) as store:
            logger.info("Odin 🍽️ starting (Signal API %s)", env.signal_api_url)
            await serve(settings.config, store, client, env, clock, stop, admin=client)
    finally:
        await client.aclose()


async def _setup(
    settings: Settings, clock: Clock, terminal: Terminal, args: argparse.Namespace
) -> int:
    env = settings.env
    client = RestSignalClient(env.signal_api_url, env.signal_number)
    try:
        if args.status:
            # Read the database if it exists; never create it here.
            if not env.db_path.exists():
                return await setup_status(client, None, settings.config, env, terminal, clock)
            with Store(env.db_path) as store:
                return await setup_status(client, store, settings.config, env, terminal, clock)
        options = SetupOptions(own_pin=args.pin, redo=frozenset(args.redo))
        with Store(env.db_path) as store:
            return await run_setup(client, store, settings.config, env, terminal, clock, options)
    finally:
        await client.aclose()


async def _list_groups(environ: Mapping[str, str]) -> None:
    signal_env = load_signal_env(environ)
    client = RestSignalClient(signal_env.signal_api_url, signal_env.signal_number)
    try:
        groups = await client.list_groups()
    finally:
        await client.aclose()
    if not groups:
        print("The bot is not a member of any group.")
    for group in sorted(groups, key=lambda g: g.name.casefold()):
        print(f"{group.name}\t{group.id}")


def _check_config(settings: Settings, clock: Clock) -> None:
    config = settings.config
    env = settings.env
    # Read the stored group IDs if the database exists; never create it here.
    if env.db_path.exists():
        with Store(env.db_path) as store:
            resolution = resolve_account(env, store)
    else:
        resolution = resolve_account(env, None)
    print(f"Config OK: {env.config_path}")
    print(f"Number:       {resolution.number}")
    for label, group in (("Flat group:  ", resolution.flat), ("Dinner group:", resolution.dinner)):
        value = f"{group.id} (from {group.source})" if group.source is not Source.UNSET else "-"
        print(f"{label} {value}")
    print(f"Database:     {env.db_path}")
    print(f"Timezone:     {config.timezone.key}")
    print(f"Emoji:        {config.emoji}")
    if resolution.account is None:
        print(f"Not set up yet ({resolution.missing}) — {SETUP_HINT}")
    print()
    print("Next scheduled actions:")
    for action in upcoming_actions(config, clock.now()):
        at = action.at.astimezone(config.timezone)
        print(f"  {at:%a %Y-%m-%d %H:%M}  {action.name} ({action.note})")
