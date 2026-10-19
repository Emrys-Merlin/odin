# Troubleshoot

**How-to guide** — steps for one task you already know you want to do.

Find out why ODIN is quiet or misbehaves: setup status, logs, common problems.

Commands on the machine run as the `odin` user (`sudo machinectl shell odin@`).

## Check the state first

```bash
systemctl --user status odin-pod signal-api odin    # all "active (running)"
podman ps                                           # odin-pod-infra, signal-api, odin
podman exec odin odin setup --status                # ✓ / ✗ per setup step
podman exec odin odin check-config                  # config, groups, next actions
```

`odin setup --status` changes nothing. It checks that the Signal API is reachable, the number is
registered, PIN, profile and hello are done, both groups are chosen and ODIN is still a
**member** of each. Its exit code is 0 when everything is fine, 1 otherwise, so it also works as a
health check after a restore or when ODIN has gone quiet. Each ✗ names what is missing; the
sections below cover the usual causes.

## Read the logs

```bash
journalctl --user -u odin -e                # the bot; -f follows, --since today
journalctl --user -u signal-api -e          # the Signal API (signal-cli's own errors)
journalctl --user -u odin-pod -e            # the pod
journalctl --user -u podman-auto-update     # updates and automatic rollbacks
```

For more detail from the bot, set the log level in `~/odin/odin.env` and restart:

```ini
ODIN_LOG_LEVEL=DEBUG
```

```bash
systemctl --user restart odin
```

Set it back to `INFO` (or remove the line) when done. The levels are listed in
[Configuration](../../reference/configuration.md).

## Problems with the units

### "Failed to connect to bus"

`systemctl --user …` fails like this when you are not in a login session of `odin`. Use
`sudo machinectl shell odin@`, not `sudo -u odin` or `su odin`.

### "Unit odin-pod.service not found"

The Quadlet generator rejected a unit file. Find out why:

```bash
/usr/libexec/podman/quadlet -dryrun -user
```

It names the file and line. Also check that the files are in `~/.config/containers/systemd/` and
that `podman --version` is 5.x.

### A unit fails right away

Read its log (`journalctl --user -u odin -e`, or `-u signal-api`, `-u odin-pod`). The full
`podman run` command line is in `systemctl --user cat odin`.

### The image pull fails

```bash
podman pull ghcr.io/emrys-merlin/odin:0
```

shows the registry's error: network, DNS, or a typo in the tag.

### The config is invalid

The bot's log shows the error and the unit restarts every 10 s.
`podman exec odin odin check-config` names the bad value; see
[Change the config](change-config.md).

## Problems in the bot's log

### "Permission denied" on `/data`

The volume belongs to the wrong uid inside the container (the bot runs as uid 1000):

```bash
podman unshare chown -R 1000:1000 "$(podman volume inspect odin-data --format '{{.Mountpoint}}')"
systemctl --user restart odin
```

### "the Signal API is not reachable"

Normal for 10–30 s after a start. If it lasts longer than a minute, check
`systemctl --user status signal-api` and its log. The bot uses `http://localhost:8080`, which
works only inside the pod: do not set `SIGNAL_API_URL` in `odin.env`.

### "ODIN is not set up yet (…)"

`odin run` waits until setup is complete. `podman exec odin odin setup --status` shows what is
missing; `podman exec -it odin odin setup` continues where it stopped. If the number is not
registered any more, see [Re-register the number](re-register-number.md).

### "odin setup is running; waiting until it has finished"

A wizard is open somewhere. Finish it; the bot resumes within 30 s. The lock of a killed wizard
expires within 2 minutes.

## Problems with Signal

### ODIN posts nothing in a group

`podman exec odin odin setup --status` shows ✗ *ODIN is not in this group* or *only invited* when
someone removed it. Add it again on your phone; see
[Change the groups](change-groups.md#odin-shows-as-invited-not-a-member).

### "Another `odin setup` is running"

Only one wizard can run at a time. Finish the first one; the lock of a killed wizard expires
within 2 minutes.

### "The Signal API call failed: …"

The wizard shows signal-cli's error message. Fix the cause (often the API restarting, or the
network) and run `podman exec -it odin odin setup` again; it continues where it stopped. The
Signal API's log has the details.

### The Signal API runs in the wrong mode

The wizard says *runs in '…' mode; ODIN needs MODE=json-rpc*. Check that
`~/.config/containers/systemd/signal-api.container` has `Environment=MODE=json-rpc`, then
`systemctl --user daemon-reload && systemctl --user restart odin-pod`.

### Sending fails with a rate-limit or "proof required" error

Signal wants a captcha before ODIN may send again (shows in the bot's log, or in the wizard's
hello or test step).

1. Solve the captcha at <https://signalcaptchas.org/challenge/generate.html> and copy the
   **"Open Signal"** link (right-click → *Copy link*). Keep its `signalcaptcha://` prefix.
2. Take the `challenge_token` from the error message.
3. Submit both from the `odin` container (the Signal API is reachable only inside the pod):

    ```bash
    podman exec -it odin python -c '
    import os, sys, httpx
    api = os.environ.get("SIGNAL_API_URL", "http://localhost:8080")
    r = httpx.post(f"{api}/v1/accounts/{os.environ["SIGNAL_NUMBER"]}/rate-limit-challenge",
                   json={"challenge_token": sys.argv[1], "captcha": sys.argv[2]})
    print(r.status_code, r.text)' '<challenge_token>' 'signalcaptcha://signal-hcaptcha.…'
    ```

The token is valid for only a minute or two, so submit it right away.

### Signal stops accepting ODIN

signal-cli is too old, usually because the Signal API image is still pinned after a
[rollback](rollback.md#the-signal-api-misbehaves-after-an-update). Set its `Image=` back to
`:latest` and update.

### You cannot find ODIN on your phone by number

After the wizard's hello step, ODIN is in your chat list; add it to groups from there.

## See also

- [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) — its
  [examples](https://github.com/bbernhard/signal-cli-rest-api/blob/master/doc/EXAMPLES.md) and
  [API](https://bbernhard.github.io/signal-cli-rest-api/)
- [signal-cli man page](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc)
- [Rootless podman tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
