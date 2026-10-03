# ODIN — Open Dinner Invitation Notifier

Signal bot that organises our weekly open Sunday dinner: asks the flat whether dinner happens,
announces it (or the cancellation) to the dinner group, and collects a rough head count.

See [docs/GOALS.md](docs/GOALS.md) for goals and design. Work is tracked in GitHub issues.

## Configuration

Behaviour (schedule, emoji, message texts) lives in a TOML file; see
[config.example.toml](config.example.toml) for all options and their defaults. Deployment values
come from env vars: `SIGNAL_NUMBER`, `FLAT_GROUP_ID`, `DINNER_GROUP_ID`, `SIGNAL_API_URL`
(default `http://localhost:8080`), `ODIB_CONFIG` (path to the TOML file) and `ODIB_DB` (path to
the SQLite database).
