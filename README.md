# ODIN — Open Dinner Invitation Notifier

Signal bot that organises our weekly open Sunday dinner: asks the flat whether dinner happens,
announces it (or the cancellation) to the dinner group, and collects a rough head count.

See [docs/GOALS.md](docs/GOALS.md) for goals and design. Work is tracked in GitHub issues.

## Configuration

Behaviour (schedule, emoji, message texts) lives in a TOML file; see
[config.example.toml](config.example.toml) for all options and their defaults. Deployment values
come from env vars: `SIGNAL_NUMBER`, `SIGNAL_API_URL` (default `http://localhost:8080`),
`ODIB_CONFIG` (path to the TOML file) and `ODIB_DB` (path to the SQLite database). The IDs of the
flat and dinner group are stored in the database by `odib setup`; the env vars `FLAT_GROUP_ID` and
`DINNER_GROUP_ID` override them when set.

## Commands

- `odib run` — run the bot: consumes reactions and checks the weekly schedule every minute.
  While ODIN is not set up (a group ID is missing) or `odib setup` is running, it waits and checks
  again every 30 s, so finishing the setup takes effect without a restart. Stops cleanly on
  SIGTERM/SIGINT.
- `odib list-groups` — print the groups ODIN is in with their IDs (for debugging, or for the
  `FLAT_GROUP_ID` / `DINNER_GROUP_ID` overrides). Needs only `SIGNAL_NUMBER` and `SIGNAL_API_URL`.
- `odib check-config` — validate the config file and env vars, show the group IDs and where they
  come from (or that ODIN is not set up yet), and print the next scheduled actions. Does not
  contact Signal.

Logs go to stdout; set the level with `ODIB_LOG_LEVEL` (default `INFO`).

## Container image

`podman build -f Containerfile -t odib .` (docker works too; without `--build-arg VERSION=…` the
image reports version `0.0.0+unknown`). Every merge to `main` is a release `vX.Y.Z`, and CI
publishes `ghcr.io/emrys-merlin/odib` with tags `X.Y.Z`, `X.Y`, `X`, `latest` and the commit SHA;
deployments follow the major tag (`:0`). `odib --version` prints the version. The
image presets `ODIB_CONFIG=/config/config.toml` and `ODIB_DB=/data/odib.db`; mount `/config` and
`/data` as volumes and pass the other env vars at run time.

## Runbooks

One-time and operational tasks that need the real bot are in [docs/runbooks](docs/runbooks):

- [signal-registration.md](docs/runbooks/signal-registration.md) — register ODIN's Signal number,
  set the PIN and profile, join the groups, get the group IDs.
