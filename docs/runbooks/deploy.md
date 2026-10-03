# Runbook: deploy ODIN on a Debian 13 VM with rootless podman

One-time setup on Proxmox, done by Tim, plus the operations that come later (upgrades, rollback,
restore). At the end:

- a **Debian 13 VM** runs ODIN as a pod of two containers (the Signal API and the bot) under a
  dedicated, unprivileged user `odin`, started at boot by systemd,
- the VM is part of the **Proxmox backup** (it holds ODIN's Signal keys),
- **`podman auto-update`** follows new ODIN releases (`ghcr.io/emrys-merlin/odin:0`) every day,
- and the last step hands over to [`odin setup`](signal-registration.md), which registers the
  number and picks the groups.

Allow an hour, most of it for the Debian install. Nothing here needs the SIM yet; that comes in
the registration runbook.

## Podman in five minutes

What the files in [`deploy/quadlet/`](../../deploy/quadlet) use, so the commands below make sense:

- **Container, image, registry** — as with docker. An *image* (`ghcr.io/emrys-merlin/odin:0`) is
  downloaded from a *registry* (GHCR, Docker Hub) and run as a *container*. podman's CLI is
  docker's: `podman ps`, `podman logs`, `podman exec`, … There is no daemon: each container is
  a normal process tree, which is what lets systemd manage it directly.
- **Rootless** — the containers run as the Linux user `odin`, not as root. Inside a container a
  process may think it is root or uid 1000, but on the VM it is a harmless unprivileged uid.
  That mapping uses a range of **subordinate uids/gids** reserved for `odin` in `/etc/subuid` and
  `/etc/subgid` (e.g. container uid 1000 → VM uid 100999). Consequence: files in the volumes
  belong to odd uids on the VM. To look at them with the container's view of ownership, run the
  command inside the user namespace: `podman unshare ls -l <path>`.
- **Volume** — storage that outlives containers. A *named volume* (`odin-signal`, `odin-data`)
  is a directory podman manages under `~/.local/share/containers/storage/volumes/`. Replacing a
  container (e.g. on update) keeps its volumes. A *bind mount* maps a normal directory into the
  container instead; we use one, read-only, for `~/odin/config`.
- **Pod** — a group of containers sharing one network namespace (the Kubernetes idea). Inside the
  pod, `localhost:8080` of the bot *is* the Signal API. Nothing is published to the VM's
  network, so the API is unreachable from outside. Every pod has a tiny extra *infra* container
  (`odin-pod-infra`) that holds the namespace.
- **Quadlet** — the systemd integration. You write short `.container`, `.pod` and `.volume`
  files in `~/.config/containers/systemd/`; on `systemctl --user daemon-reload` a systemd
  *generator* turns each into a normal service with the full `podman run …` command line.
  `odin.container` → `odin.service`, `signal-api.container` → `signal-api.service`,
  `odin.pod` → `odin-pod.service`, `odin-signal.volume` → `odin-signal-volume.service`. These
  generated units cannot be `systemctl enable`d; the `[Install]` section in the source file does
  that job. The containers' logs go to the journal.
- **systemd user instance and lingering** — every logged-in user has their own systemd
  (`systemctl --user`, `journalctl --user`). Normally it stops at logout; **lingering**
  (`loginctl enable-linger odin`) starts it at boot and keeps it running, so ODIN runs without
  anyone logged in.
- **Auto-update** — containers labelled `AutoUpdate=registry` are checked by
  `podman auto-update`: if the registry has a newer image for the same tag, podman pulls it and
  restarts the unit; if the restarted unit fails, it rolls back to the previous image. A user
  timer runs it daily.

## 1. Create the VM (Proxmox web UI)

1. **Get the installer.** Node → `local` storage → *ISO Images* → *Download from URL*:
   the current `debian-13.*-amd64-netinst.iso` from
   <https://www.debian.org/CD/netinst/> (copy the link of the *amd64* netinst image).
2. **Create VM** (top right):
   - *General*: name `odin`. Note the VM ID.
   - *OS*: the Debian 13 ISO; type Linux, 6.x kernel.
   - *System*: tick **Qemu Agent** (lets backups freeze the filesystem consistently).
   - *Disks*: **10 GB**, bus VirtIO SCSI (single), tick *Discard* if the storage is thin.
   - *CPU*: **1** core, type `host` (or the default).
   - *Memory*: **1536** MiB.
   - *Network*: default bridge (`vmbr0`), model VirtIO.
   - *Confirm*, tick *Start after created*.
3. **Install Debian** in the VM's console:
   - Language/keyboard as you like; hostname `odin`.
   - Leave the **root password empty** — then the first user gets `sudo`. Create your admin
     user (e.g. `tim`).
   - Partitioning: *Guided – use entire disk*, all files in one partition.
   - Software selection: untick the desktop environment; tick **SSH server** and
     **standard system utilities** only.
4. After the reboot, log in over SSH as your admin user (`ssh tim@<vm-ip>`; the IP is on the
   console or in the VM's *Summary* once the guest agent runs) and update:

   ```bash
   sudo apt update && sudo apt full-upgrade -y
   ```

## 2. Back it up — before anything else

The Signal API's volume will hold ODIN's account keys. Losing them means registering the number
again, which needs the SIM. So set the backup up now, not later:

1. Datacenter → *Backup* → *Add*:
   - *Node/Storage*: your backup storage (Proxmox Backup Server or a directory storage).
   - *Schedule*: daily (e.g. `03:00`).
   - *Selection mode*: *Include selected VMs*, tick `odin`.
   - *Mode*: **Snapshot**.
   - *Retention*: e.g. keep-daily 7, keep-weekly 4, keep-monthly 6.
2. The backups contain ODIN's private keys: the backup storage must be as private as a password
   manager (no shared/public storage).

After `odin setup` (step 8) you run this job once by hand and check it.

## 3. Install podman and create the `odin` user (as admin)

```bash
sudo apt install -y podman systemd-container dbus-user-session qemu-guest-agent git
sudo systemctl enable --now qemu-guest-agent
podman --version     # must be 5.x (Debian 13 ships 5.4); .pod files need >= 5.0
```

`podman` pulls in `uidmap` (subuid support) and `passt` (rootless networking).
`systemd-container` provides `machinectl` (below), `dbus-user-session` the per-user D-Bus that
`systemctl --user` needs.

Create the user that runs ODIN — no password, nobody logs in as it directly:

```bash
sudo adduser --disabled-password --comment "ODIN bot" odin
grep odin /etc/subuid /etc/subgid
```

`grep` must print a line for each file, e.g. `/etc/subuid:odin:100000:65536`. (Debian's
`adduser` assigns the range automatically.) If it prints nothing:

```bash
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 odin
```

Enable lingering, so `odin`'s systemd — and with it ODIN — starts at boot:

```bash
sudo loginctl enable-linger odin
```

**Become `odin`** — with `machinectl`, not `sudo -u` or `su`: only a real login session sets up
`systemctl --user` (with `sudo -u` it fails with *Failed to connect to bus*):

```bash
sudo machinectl shell odin@
```

Every following command runs as `odin` in this shell; `exit` leaves it. Check:

```bash
systemctl --user status        # "State: running"
podman info --format '{{.Host.Security.Rootless}}'   # true
```

## 4. Install the files (as `odin`)

Layout on the VM:

| Path | What |
|------|------|
| `~/odin-src/` | a clone of this repo; source of the unit files and the example config |
| `~/.config/containers/systemd/` | the Quadlet units (where podman's generator looks) |
| `~/odin/odin.env` | env file: `SIGNAL_NUMBER`, optional overrides |
| `~/odin/config/config.toml` | the config: schedule, emoji, message texts (mounted read-only at `/config`) |

```bash
git clone https://github.com/Emrys-Merlin/odin.git ~/odin-src
mkdir -p ~/.config/containers/systemd ~/odin/config
cp ~/odin-src/deploy/quadlet/*.pod ~/odin-src/deploy/quadlet/*.container \
   ~/odin-src/deploy/quadlet/*.volume ~/.config/containers/systemd/
cp ~/odin-src/deploy/quadlet/odin.env.example ~/odin/odin.env
cp ~/odin-src/config.example.toml ~/odin/config/config.toml
chmod 600 ~/odin/odin.env
```

1. **`~/odin/odin.env`** (`nano ~/odin/odin.env`): set `SIGNAL_NUMBER` to ODIN's number, E.164
   (`+49…`, no spaces). Leave `FLAT_GROUP_ID` / `DINNER_GROUP_ID` commented out — `odin setup`
   stores the group IDs in the database.
2. **`~/odin/config/config.toml`**: adjust times and texts if you want; the defaults are the
   agreed weekly cycle. For a profile picture, put it next to it (e.g.
   `~/odin/config/odin.png`) and set `avatar = "odin.png"` under `[profile]`.

Check the config with the real image before starting anything (`check-config` does not contact
Signal; `--rm` removes the container afterwards):

```bash
podman run --rm --env-file ~/odin/odin.env -v ~/odin/config:/config:ro \
  ghcr.io/emrys-merlin/odin:0 check-config
```

It prints the schedule's next actions and says ODIN is not set up yet — that is expected. An
error names the bad value; fix it and run again.

Check that Quadlet understands the units (prints the generated services; errors name the file
and line):

```bash
/usr/libexec/podman/quadlet -dryrun -user
```

## 5. Start

```bash
systemctl --user daemon-reload          # runs the Quadlet generator
systemctl --user start odin-pod         # creates the volumes, the pod, both containers
```

The first start pulls both images, which can take a minute or two. Then:

```bash
systemctl --user status odin-pod signal-api odin    # all "active (running)"
podman pod ps                                       # odin-pod, Running, 3 containers
podman ps                                           # odin-pod-infra, signal-api, odin
podman volume ls                                    # odin-signal, odin-data
journalctl --user -u odin -f                        # Ctrl-C to stop following
```

The bot's log should say, after the Signal API has started (10–30 s):

```text
ODIN is not set up yet (…) — run: podman exec -it odin odin setup
```

That is the expected state: `odin run` waits, and the container keeps running. (Before the
Signal API is up it logs that the API is not reachable yet; also fine.)

The Signal API's log: `journalctl --user -u signal-api`. It should end with signal-cli's daemon
listening; warnings about no accounts being registered are normal now.

**Check the start at boot once:** `sudo reboot` (from your admin shell), wait a minute, log in,
`sudo machinectl shell odin@`, `podman ps` — both containers run again without you starting
anything.

## 6. Automatic updates

```bash
systemctl --user enable --now podman-auto-update.timer
systemctl --user list-timers         # shows podman-auto-update.timer and its next run
podman auto-update --dry-run         # what would be updated now; "false" = up to date
```

The timer runs daily around midnight. Both containers are updated:

- **odin** follows the major tag `:0`: every `0.x` release, never `1.0.0`. Going live is a
  manual step (see [Major upgrade](#major-upgrade-going-live)).
- **signal-api** follows `:latest`. signal-cli has to stay current anyway — Signal stops
  accepting clients that are a few months old. If an update breaks it, pin it
  ([Rollback](#rollback)).

## 7. Set up ODIN's Signal account

```bash
podman exec -it odin odin setup
```

Follow [signal-registration.md](signal-registration.md): it registers the number, sets the PIN
and profile, and picks the flat and dinner group. The running bot notices within 30 s that setup
is done and starts; no restart needed.

## 8. Back up after setup

Proxmox → Datacenter → *Backup* → select the job → *Run now*. When it has finished, the VM's
*Backup* tab lists a backup with today's date. From now on the daily job keeps the keys safe.

Done. ODIN asks the flat group on the next Tuesday.

---

## Operations

All as `odin` (`sudo machinectl shell odin@`).

| Task | Command |
|------|---------|
| Status | `systemctl --user status odin-pod signal-api odin` · `podman ps` |
| Bot log | `journalctl --user -u odin` (`-f` follows, `--since today`) |
| Signal API log | `journalctl --user -u signal-api` |
| Setup state | `podman exec odin odin setup --status` |
| Next actions | `podman exec odin odin check-config` |
| Restart the bot | `systemctl --user restart odin` |
| Stop / start everything | `systemctl --user stop odin-pod` / `systemctl --user start odin-pod` |

- **Changed `config.toml` or `odin.env`:** `systemctl --user restart odin`. Config errors show
  in its log; the unit restarts every 10 s until the config is fixed.
- **Changed unit files** (new version in the repo):

  ```bash
  git -C ~/odin-src pull
  cp ~/odin-src/deploy/quadlet/*.pod ~/odin-src/deploy/quadlet/*.container \
     ~/odin-src/deploy/quadlet/*.volume ~/.config/containers/systemd/
  systemctl --user daemon-reload
  systemctl --user restart odin-pod
  ```

  Also compare `config.example.toml` with your `config.toml` when a release notes a config
  change (`diff ~/odin-src/config.example.toml ~/odin/config/config.toml`).

### Upgrade

Nothing to do for `0.x` releases: the timer pulls them. To upgrade right away:
`podman auto-update`. `podman exec odin odin --version` shows the running version.

### Major upgrade (going live)

A major release (`1.0.0`) is never pulled automatically. Read its release notes, then change the
tag in **`~/.config/containers/systemd/odin.container`** (`Image=ghcr.io/emrys-merlin/odin:1`;
the repo's copy gets the same change in the going-live PR) and:

```bash
systemctl --user daemon-reload
systemctl --user restart odin
podman exec odin odin --version
```

### Rollback

- **Automatic:** if a restarted unit fails to start after an update, `podman auto-update` puts
  the previous image back by itself (`journalctl --user -u podman-auto-update` shows it).
- **Manual:** a release starts but misbehaves. Pin the last good version — exact tags never
  move, so auto-update leaves it alone — in `~/.config/containers/systemd/odin.container`:

  ```ini
  Image=ghcr.io/emrys-merlin/odin:0.4.0
  ```

  then `systemctl --user daemon-reload && systemctl --user restart odin`. Versions are listed
  under the repo's *Releases*. Check the release notes when going back across a change to the
  database: an older version may not read a newer database. Once a fixed release is out, set
  `Image=` back to `:0` the same way.
- **Signal API:** the same in `signal-api.container`, with a tag from
  <https://hub.docker.com/r/bbernhard/signal-cli-rest-api/tags>, e.g.
  `Image=docker.io/bbernhard/signal-cli-rest-api:0.101`. Remember to unpin later, or signal-cli
  gets too old for Signal.

### Restore from backup

- **Whole VM** (disk lost, VM broken, bad change): Proxmox → VM `odin` → *Backup* → pick a
  backup → *Restore* (overwrites the VM; stop it first). After it boots, ODIN starts by itself.
  Check with `podman exec odin odin setup --status`. An old backup is fine: Signal keys do not
  expire. Actions due while ODIN was down are caught up within the grace window, and nothing that
  the restored database records as sent is sent again.
- **One volume from a tarball** (an extra copy made with `podman volume export`, see
  [signal-registration.md](signal-registration.md#backing-up-the-volume--mandatory)):

  ```bash
  systemctl --user stop odin-pod
  podman volume rm odin-signal
  podman volume create odin-signal
  podman volume import odin-signal odin-signal-2026-10-04.tar
  systemctl --user start odin-pod
  ```

  The same works for `odin-data` (the database: what was sent, reactions, chosen groups).
  Without it, ODIN would ask for the groups again (`odin setup`) and could repeat this week's
  messages.

**Never run a second copy of the deployment** (e.g. a restored VM next to the original): two
signal-cli instances on the same account break it.

## Troubleshooting

- **`systemctl --user …` says *Failed to connect to bus*:** you are not in a login session of
  `odin`. Use `sudo machinectl shell odin@`, not `sudo -u odin` / `su odin`.
- **`systemctl --user start odin-pod` says *Unit odin-pod.service not found*:** the generator
  rejected a unit file. `/usr/libexec/podman/quadlet -dryrun -user` names the problem. Check
  that the files are in `~/.config/containers/systemd/` and that podman is 5.x.
- **A unit fails right away:** `journalctl --user -u odin -e` (or `-u signal-api`,
  `-u odin-pod`). The full `podman run` command is in `systemctl --user cat odin`.
- **The image pull fails:** `podman pull ghcr.io/emrys-merlin/odin:0` shows the registry's error
  (network, DNS, typo in the tag).
- **The bot logs *Permission denied* on `/data`:** the volume belongs to the wrong uid inside the
  container (the bot runs as uid 1000). Fix:

  ```bash
  podman unshare chown -R 1000:1000 "$(podman volume inspect odin-data --format '{{.Mountpoint}}')"
  systemctl --user restart odin
  ```

- **The bot says the Signal API is not reachable** for more than a minute:
  `systemctl --user status signal-api` and its log. The bot uses `http://localhost:8080`, which
  works only inside the pod — do not set `SIGNAL_API_URL` in `odin.env`.
- **Anything about registration, groups or sending:** see the troubleshooting section of
  [signal-registration.md](signal-registration.md#troubleshooting).

## References

- [podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
  — every Quadlet key used in `deploy/quadlet/`
- [podman-auto-update(1)](https://docs.podman.io/en/latest/markdown/podman-auto-update.1.html)
- [Rootless podman tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
- [Proxmox VE: Backup and Restore](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
- [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) (`MODE=json-rpc`,
  data in `/home/.local/share/signal-cli`)
