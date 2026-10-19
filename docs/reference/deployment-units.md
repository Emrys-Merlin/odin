# Deployment units

**Reference** — exact facts to look up.

The Quadlet units, volumes and container image tags.

ODIN runs as two containers in one podman pod, defined by the
[Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) files in
[`deploy/quadlet/`](https://github.com/Emrys-Merlin/odin/tree/main/deploy/quadlet). They are
written for rootless podman ≥ 5.0 under a dedicated user, installed in
`~/.config/containers/systemd/`. Installing them is part of
[First deployment](../tutorials/first-deployment.md).

## Files

| File | Defines | systemd service |
|---|---|---|
| `odin.pod` | the pod `odin-pod` | `odin-pod.service` |
| `signal-api.container` | the container `signal-api` (signal-cli-rest-api) | `signal-api.service` |
| `odin.container` | the container `odin` (the bot) | `odin.service` |
| `odin-signal.volume` | the named volume `odin-signal` | `odin-signal-volume.service` |
| `odin-data.volume` | the named volume `odin-data` | `odin-data-volume.service` |
| `odin.env.example` | template of the env file `~/odin/odin.env`; not a unit | — |

Every unit except the volumes has `WantedBy=default.target`, so it starts with the user's
systemd instance (at boot, with lingering enabled).

### `odin.pod`

| Setting | Value | Effect |
|---|---|---|
| `PodName` | `odin-pod` | Not `odin`: pods and containers share one name space, and the bot container is `odin`. |

Both containers share the pod's network namespace: `odin` reaches the Signal API at
`http://localhost:8080`. No port is published to the host.

### `signal-api.container`

| Setting | Value |
|---|---|
| `ContainerName` | `signal-api` |
| `Pod` | `odin.pod` |
| `Image` | `docker.io/bbernhard/signal-cli-rest-api:latest` |
| `AutoUpdate` | `registry` |
| `Environment` | `MODE=json-rpc` |
| `Volume` | `odin-signal.volume:/home/.local/share/signal-cli` |
| `Restart` / `RestartSec` | `always` / `10` |
| `TimeoutStartSec` | `900` (the first start pulls the image) |

### `odin.container`

| Setting | Value |
|---|---|
| `ContainerName` | `odin` |
| `Pod` | `odin.pod` |
| `Wants` / `After` | `signal-api.service` |
| `Image` | `ghcr.io/emrys-merlin/odin:0` — the major tag, see [Image tags](#image-tags) |
| `AutoUpdate` | `registry` |
| `EnvironmentFile` | `%h/odin/odin.env` |
| `Volume` | `%h/odin/config:/config:ro` |
| `Volume` | `odin-data.volume:/data` |
| `Restart` / `RestartSec` | `always` / `10` |
| `TimeoutStartSec` | `900` |

`%h` is the home directory of the user running the units. The image's default command is
`odin run`, which waits instead of exiting while ODIN is not set up, so the container keeps
running and `podman exec -it odin odin setup` works.

### Volumes and mounts

| Host side | Container | Mounted in | Holds |
|---|---|---|---|
| volume `odin-signal` | `/home/.local/share/signal-cli` | `signal-api` | signal-cli data: ODIN's Signal account keys. Losing it means registering the number again. Must be backed up. |
| volume `odin-data` | `/data` | `odin` | the state database `odin.db`: sent actions, reactions, chat changes, the chosen group IDs |
| directory `~/odin/config` | `/config`, read-only | `odin` | `config.toml` and an optional avatar image next to it |

Named volumes are created on the first start of their service and are not removed by stopping
or removing the containers. Backing them up: [Back up and restore](../how-to/operate/backup-restore.md).

### `odin.env.example`

Copied to `~/odin/odin.env` (mode `600`). Format: `KEY=value`, one per line, no quotes, no
spaces around `=`.

| Variable | In the example |
|---|---|
| `SIGNAL_NUMBER` | set, placeholder `+49XXXXXXXXXXX` |
| `FLAT_GROUP_ID`, `DINNER_GROUP_ID` | commented out |
| `ODIN_LOG_LEVEL` | commented out, `INFO` |

`SIGNAL_API_URL`, `ODIN_CONFIG` and `ODIN_DB` are not in the env file: the default URL and the
image presets fit the pod. All variables: [Configuration](configuration.md#environment-variables).

## Container image

`ghcr.io/emrys-merlin/odin`, public, built from
[`Containerfile`](https://github.com/Emrys-Merlin/odin/blob/main/Containerfile).

### Image tags

Every release `vX.Y.Z` pushes the same image under these tags:

| Tag | Example (`v0.4.2`) | Points to |
|---|---|---|
| `X.Y.Z` | `0.4.2` | exactly this release |
| `X.Y` | `0.4` | the latest release of `0.4` |
| `X` | `0` | the latest release of major version `0` |
| `latest` | `latest` | the latest release |
| commit SHA | full 40-character SHA | the image built from that commit of `main` |

Deployments follow the major tag (`:0` before going live, `:1` after), not `latest`:
`podman auto-update` then pulls new minor and patch releases but never a new major version.
A new major version means editing `Image=` in `odin.container`. `release:none` merges push no
image. How releases are made: [Release](../how-to/develop/release.md).

### Image presets

| Preset | Value |
|---|---|
| `ENTRYPOINT` | `odin` |
| `CMD` | `run` |
| `ODIN_CONFIG` | `/config/config.toml` |
| `ODIN_DB` | `/data/odin.db` |
| `VOLUME` | `/config`, `/data` |
| `USER` | `odin` (UID 1000, GID 1000); owns `/data` |
| `WORKDIR` | `/app` |
| `PYTHONUNBUFFERED` | `1` (logs reach stdout at once) |

Labels: `org.opencontainers.image.version` (the release version, `X.Y.Z`) and
`org.opencontainers.image.revision` (the commit SHA). An image built locally without
`--build-arg VERSION=…` reports version `0.0.0+unknown`.
