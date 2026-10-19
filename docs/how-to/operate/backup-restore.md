# Back up and restore on Proxmox

**How-to guide** — steps for one task you already know you want to do.

Back up ODIN's volumes on a Proxmox VE deployment, and restore them.

This page assumes ODIN runs in a VM on [Proxmox VE](https://www.proxmox.com/en/proxmox-virtual-environment)
and is backed up by a Proxmox backup job. On another host, use whatever backs up that machine
in place of the Proxmox sections; the [volume tarball](#make-an-extra-copy-of-a-volume) sections
work wherever ODIN runs on podman.

Two volumes hold everything ODIN needs to survive ([Deployment units](../../reference/deployment-units.md)):

- `odin-signal` — ODIN's Signal account keys. Losing it means
  [registering the number again](re-register-number.md), which needs the SIM.
- `odin-data` — the state database: what was sent, reactions, the chosen groups.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

!!! danger "Never run a second copy"

    Never start a restored VM or volume next to the running one, and never register ODIN's
    number on another machine while the deployment holds the account. Two signal-cli instances
    on the same account break it.

## Back up the VM with Proxmox

A backup of the whole VM covers both volumes.

1. Proxmox → Datacenter → *Backup* → *Add*:
    - *Node/Storage*: your backup storage (Proxmox Backup Server or a directory storage).
    - *Schedule*: daily, e.g. `03:00`.
    - *Selection mode*: *Include selected VMs*, tick `odin`.
    - *Mode*: **Snapshot**.
    - *Retention*: e.g. keep-daily 7, keep-weekly 4, keep-monthly 6.
2. Use backup storage that is as private as a password manager: the backups contain ODIN's
   private keys.
3. Tick **Qemu Agent** in the VM's *Options* (and run `qemu-guest-agent` in the VM), so snapshots
   freeze the filesystem consistently.

## Check the backup after setup

After `odin setup` (and after any re-registration), the backup must contain the keys:

1. Proxmox → Datacenter → *Backup* → select the job → *Run now*.
2. When it has finished, the VM's *Backup* tab lists a backup with today's date.

## Make an extra copy of a volume

Works on any host. Before a risky change (re-registering, a rollback across a database change),
export the volumes to tarballs:

```bash
podman volume export odin-signal --output odin-signal-$(date +%F).tar
podman volume export odin-data --output odin-data-$(date +%F).tar
```

The `odin-signal` tarball contains the account keys: store it encrypted, like a password, never
in the repo. To see where a volume is on disk:
`podman volume inspect odin-signal --format '{{.Mountpoint}}'`.

## Restore the whole VM

For a lost disk, a broken VM or a bad change:

1. Proxmox → VM `odin` → *Shutdown*.
2. VM `odin` → *Backup* → pick a backup → *Restore*. This overwrites the VM.
3. Start the VM. ODIN starts by itself.
4. Check it, as `odin`:

    ```bash
    podman exec odin odin setup --status
    ```

    Every line shows ✓ and the exit code is 0.

An old backup is fine: Signal keys do not expire. Messages Signal delivered while the backup was
offline are lost, which does not matter for ODIN. Actions that fell due while ODIN was down are
caught up within the grace window, and nothing the restored database records as sent goes out
again ([Reliability](../../explanation/reliability.md)).

## Restore one volume from a tarball

Works on any host.

```bash
systemctl --user stop odin-pod
podman volume rm odin-signal
podman volume create odin-signal
podman volume import odin-signal odin-signal-2026-10-04.tar
podman unshare chown 1000:1000 "$(podman volume inspect -f '{{.Mountpoint}}' odin-signal)"
systemctl --user start odin-pod
podman exec odin odin setup --status
```

The `chown` is needed: the tarball does not record the owner of the volume's root directory, so
after the import it belongs to root inside the containers, and both containers run as uid 1000.
Without it, creating a file at the top of the volume fails with *Permission denied*.

For `odin-data`, do the same with `odin-data` in every line, `chown` included. Without the
database, ODIN asks for the groups again (`odin setup`) and could repeat this week's messages.

## See also

- [Proxmox VE: Backup and Restore](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
- [Re-register the number](re-register-number.md) — when there is no backup of `odin-signal`
