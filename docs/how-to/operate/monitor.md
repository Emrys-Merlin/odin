# Monitor ODIN

**How-to guide** — steps for one task you already know you want to do.

Check whether ODIN can do its job, and get alerted by an external monitor when it cannot.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

ODIN answers `GET /health` on port 8081 inside the pod. What its answer means:
[Health endpoint](../../reference/health-endpoint.md).

## Check the health on the host

```bash
podman exec odin odin health        # "up" or "down", with the reasons; exit code 0 when up
podman ps                           # odin shows "(healthy)", "(unhealthy)" or "(starting)"
podman healthcheck run odin         # runs Podman's check now; prints "healthy" or the output
```

Podman's own check runs `odin health --setup-ok` every 30 s, so it also passes while ODIN only
waits for `odin setup`; `odin health` without the option does not.

## Publish the port

Nothing is published by default. To let a monitor outside the pod reach the endpoint, publish
it on one host address only — one that your monitor can reach and others cannot:

1. Add a `PublishPort=` line to the `[Pod]` section of `~/.config/containers/systemd/odin.pod`,
   for example `127.0.0.1` for a monitor on the same machine:

    ```ini
    PublishPort=127.0.0.1:8081:8081
    ```

    or the machine's address in a private network or VPN that the monitor is in (a LAN address,
    a WireGuard or Tailscale address, …):

    ```ini
    PublishPort=192.168.1.20:8081:8081
    ```

    Avoid publishing it without an address (`8081:8081`): that opens it on every interface of
    the machine. The body holds no personal data, but there is no reason to show it to anyone.

2. Reload and restart the pod (both containers restart):

    ```bash
    systemctl --user daemon-reload && systemctl --user restart odin-pod
    ```

3. Check it from a machine that should reach it:

    ```bash
    curl -i http://192.168.1.20:8081/health
    ```

    The first line is `HTTP/1.1 200 OK` while ODIN is up.

## Set up a monitor

Any monitor that can check an HTTP URL works (Uptime Kuma, Gatus, Healthchecks with a cron job,
a hosted uptime service that can reach the address, …). Configure it like this:

1. **URL**: `http://<published address>:8081/health`.
2. **Up** means HTTP status `200`; ODIN answers `503` when it is down. If the monitor can check
   JSON, `status` is `up` or `down` as well.
3. **Interval**: about a minute is plenty. Allow 2–3 failed checks before alerting, so a restart
   (ODIN is `starting` for a few seconds, longer after an update) does not alert.
4. **Alerts**: send them through a channel that does **not** depend on ODIN's Signal API — e-mail,
   ntfy, another messenger. A Signal notification would need the same `signal-api` container that
   may be the reason ODIN is down.

For example, in Uptime Kuma: **Add New Monitor**, type *HTTP(s)* (or *HTTP(s) - Json Query* with
the query `status` and the expected value `up`), the URL above, and **Retries** 2.

When the monitor reports ODIN down, the reasons in the body (or `podman exec odin odin health`)
say what is wrong; [Troubleshoot](troubleshoot.md) covers the usual causes.

## Turn the endpoint off

Set `ODIN_HEALTH_PORT=0` in `~/odin/odin.env` and remove the `HealthCmd=` and `Notify=healthy`
lines from `~/.config/containers/systemd/odin.container` (without the endpoint, the check never
passes and the unit never counts as started). Then:

```bash
systemctl --user daemon-reload && systemctl --user restart odin
```
