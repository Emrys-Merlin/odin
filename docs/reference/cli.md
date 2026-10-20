# CLI

**Reference** — exact facts to look up.

Every `odin` subcommand and option. The env vars and the config file are described in
[Configuration](configuration.md); how the commands fit into a deployment is in the
[first deployment tutorial](../tutorials/first-deployment.md).

In the container image `odin` is the entry point and `run` the default command (see
[Deployment units](deployment-units.md)).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. For `odin setup --status`: ODIN is fully set up. For `odin health`: ODIN is up (with `--setup-ok`: or only waits for `odin setup`). |
| `1` | A Signal API, HTTP or database error (printed as `odin: <Error>: <message>`). For `odin setup`: the wizard stopped before ODIN was set up; for `odin setup --status`: a step is missing; for `odin health`: ODIN is down, does not answer, or the endpoint is off (`ODIN_HEALTH_PORT=0`). |
| `2` | A configuration error (`odin: configuration error: …`), or invalid arguments. |
| `130` | Interrupted with Ctrl+C. |

--8<-- "docs/reference/_generated/cli.md"
