# Upgrade

**How-to guide** — steps for one task you already know you want to do.

Let auto-update follow new releases, upgrade by hand, and move to a new major version.

All commands run as the `odin` user on the machine: `sudo machinectl shell odin@` (not `sudo -u` or
`su`, see [Troubleshoot](troubleshoot.md#failed-to-connect-to-bus)).

## Turn on automatic updates

```bash
systemctl --user enable --now podman-auto-update.timer
systemctl --user list-timers         # shows podman-auto-update.timer and its next run
podman auto-update --dry-run         # what would be updated now; "false" = up to date
```

The timer runs daily around midnight and updates both containers: `odin` within its major tag
(`:0` pulls every `0.x` release, never `1.0.0`), `signal-api` on `:latest`. Which tag each unit
follows is listed in [Deployment units](../../reference/deployment-units.md).

## Upgrade right away

Nothing to do for a minor or patch release except waiting for the timer. To take it now:

```bash
podman auto-update
podman exec odin odin --version      # the running version
```

If the new image fails to start, `podman auto-update` puts the previous one back; see
[Roll back](rollback.md).

## Upgrade to a new major version (going live)

A major release (`1.0.0`) is never pulled automatically.

1. Read its release notes on the repo's
   [Releases](https://github.com/Emrys-Merlin/odin/releases) page. Apply any config change they
   name ([Change the config](change-config.md)).
2. Change the tag in `~/.config/containers/systemd/odin.container`:

    ```ini
    Image=ghcr.io/emrys-merlin/odin:1
    ```

    The repo's copy of the unit gets the same change in the going-live PR.

3. Reload and restart:

    ```bash
    systemctl --user daemon-reload
    systemctl --user restart odin
    podman exec odin odin --version
    ```

From now on auto-update follows `1.x`.

## Update the unit files

When a release changes the files in `deploy/quadlet/`:

```bash
git -C ~/odin-src pull
cp ~/odin-src/deploy/quadlet/*.pod ~/odin-src/deploy/quadlet/*.container \
   ~/odin-src/deploy/quadlet/*.volume ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user restart odin-pod
```

This overwrites local edits to the units, e.g. a pinned `Image=` from a [rollback](rollback.md);
make them again afterwards. When a release notes a config change, also compare the example
config with yours:

```bash
diff ~/odin-src/config.example.toml ~/odin/config/config.toml
```

## See also

- [podman-auto-update(1)](https://docs.podman.io/en/latest/markdown/podman-auto-update.1.html)
- [podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
  — the Quadlet keys
- [Release](../develop/release.md) — how releases and tags are made
