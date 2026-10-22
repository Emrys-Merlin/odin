# Roll back

**How-to guide** — steps for one task you already know you want to do.

Go back to an earlier image.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

## A new image does not start

Nothing to do: when a unit fails to start after an update, `podman auto-update` puts the previous
image back by itself. For `odin`, "started" means healthy (`Notify=healthy`): an image whose bot
runs but stays unhealthy for 15 minutes — say, it never reaches the Signal API, never finishes a
tick or never opens its event connection — is rolled back too. Check that it did:

```bash
journalctl --user -u podman-auto-update
podman exec odin odin --version
```

## A release starts but misbehaves

Pin the last good version. Exact version tags never move, so auto-update leaves a pinned unit
alone.

1. Find the last good version on the repo's
   [Releases](https://github.com/Emrys-Merlin/odin/releases) page. Read the release notes of the
   versions you skip back over: an older version may not read a database changed by a newer
   one (see [Schema version](../../reference/state-database.md#schema-version)).
2. Set it in `~/.config/containers/systemd/odin.container`:

    ```ini
    Image=ghcr.io/emrys-merlin/odin:0.4.0
    ```

3. Reload and restart:

    ```bash
    systemctl --user daemon-reload && systemctl --user restart odin
    podman exec odin odin --version
    ```

Once a fixed release is out, set `Image=` back to the major tag (`ghcr.io/emrys-merlin/odin:0`)
the same way, so auto-update follows releases again.

## The Signal API misbehaves after an update

The same, in `~/.config/containers/systemd/signal-api.container`, with a tag from
[Docker Hub](https://hub.docker.com/r/bbernhard/signal-cli-rest-api/tags):

```ini
Image=docker.io/bbernhard/signal-cli-rest-api:0.101
```

```bash
systemctl --user daemon-reload && systemctl --user restart signal-api
```

Unpin it (back to `:latest`) as soon as a fixed version is out: Signal stops accepting clients
that are a few months old.

## Roll back the whole machine

For a bad change that is not about the image (a broken database, a botched edit on the
machine), restore a backup instead: the whole machine from your host's backup (on Proxmox:
[restore the whole VM](backup-restore.md#restore-the-whole-vm)), or a single volume
[from a tarball](backup-restore.md#restore-one-volume-from-a-tarball).
