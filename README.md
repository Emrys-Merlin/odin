# ODIN — Open Dinner Invitation Notifier

Signal bot that organises our weekly open Sunday dinner: asks the flat whether dinner happens,
announces it (or the cancellation) to the dinner group, and collects a rough head count.

See [docs/GOALS.md](docs/GOALS.md) for goals and design. Work is tracked in GitHub issues.

## Configuration

Behaviour (schedule, emoji, message texts) lives in a TOML file; see
[config.example.toml](config.example.toml) for all options and their defaults. Deployment values
come from env vars: `SIGNAL_NUMBER`, `SIGNAL_API_URL` (default `http://localhost:8080`),
`ODIN_CONFIG` (path to the TOML file) and `ODIN_DB` (path to the SQLite database). The profile
name and picture and the texts `odin setup` sends are in the TOML file too. The IDs of the flat
and dinner group are stored in the database by `odin setup`; the env vars `FLAT_GROUP_ID` and
`DINNER_GROUP_ID` override them when set.

## Commands

- `odin run` — run the bot: consumes reactions and checks the weekly schedule every minute.
  While ODIN is not set up (number not registered, or a group ID missing), the Signal API is not
  reachable, or `odin setup` is running, it waits and checks again every 30 s, so finishing the
  setup takes effect without a restart. Stops cleanly on SIGTERM/SIGINT.
- `odin setup` — interactive setup, run inside the container (`podman exec -it odin odin setup`):
  registers ODIN's number (captcha, SMS or voice code), sets the PIN and profile, exchanges a
  hello with the operator and lets them pick the flat and dinner group. Every finished step is
  skipped, so it can be stopped and run again at any time. `--status` only shows what is done
  (exit code 0 when fully set up; usable as a health check), `--pin` sets an own PIN,
  `--redo pin|hello|groups|test` repeats a finished step. It never registers an already
  registered number again (see the registration runbook). While it runs, `odin run` pauses.
- `odin list-groups` — print the groups ODIN is in with their IDs (for debugging, or for the
  `FLAT_GROUP_ID` / `DINNER_GROUP_ID` overrides). Needs only `SIGNAL_NUMBER` and `SIGNAL_API_URL`.
- `odin check-config` — validate the config file and env vars, show the group IDs and where they
  come from (or that ODIN is not set up yet), and print the next scheduled actions. Does not
  contact Signal.

Logs go to stdout; set the level with `ODIN_LOG_LEVEL` (default `INFO`).

## Container image

`podman build -f Containerfile -t odin .` (docker works too; without `--build-arg VERSION=…` the
image reports version `0.0.0+unknown`). Every merge to `main` is a release `vX.Y.Z`, and CI
publishes `ghcr.io/emrys-merlin/odin` with tags `X.Y.Z`, `X.Y`, `X`, `latest` and the commit SHA;
deployments follow the major tag (`:0`). `odin --version` prints the version. The
image presets `ODIN_CONFIG=/config/config.toml` and `ODIN_DB=/data/odin.db`; mount `/config` and
`/data` as volumes and pass the other env vars at run time.

## Runbooks

One-time and operational tasks that need the real bot are in [docs/runbooks](docs/runbooks):

- [deploy.md](docs/runbooks/deploy.md) — run ODIN on a Debian 13 VM on Proxmox with rootless
  podman and the Quadlet units in [deploy/quadlet](deploy/quadlet): install, auto-update,
  upgrade, rollback, restore from backup.
- [signal-registration.md](docs/runbooks/signal-registration.md) — set up ODIN's Signal account
  with `odin setup`: what each step asks, `--status`, the options, backups and troubleshooting.
