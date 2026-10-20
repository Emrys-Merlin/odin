# Monitor ODIN

**How-to guide** — steps for one task you already know you want to do.

Check whether ODIN can do its job, and get alerted by Uptime Kuma when it cannot.

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

ODIN answers `GET /health` on port 8081 inside the pod. What its answer means:
[Health endpoint](../../reference/health-endpoint.md).

## Check the health on the VM

```bash
podman exec odin odin health        # "up" or "down", with the reasons; exit code 0 when up
podman ps                           # odin shows "(healthy)", "(unhealthy)" or "(starting)"
podman healthcheck run odin         # runs Podman's check now; prints "healthy" or the output
```

Podman's own check runs `odin health --setup-ok` every 30 s, so it also passes while ODIN only
waits for `odin setup`; `odin health` without the option does not.

## Publish the port

Nothing is published by default. Publish the endpoint on one host address only:

1. Add a `PublishPort=` line to the `[Pod]` section of `~/.config/containers/systemd/odin.pod`:
   the VM's Tailscale address, so only the tailnet reaches it,

    ```ini
    PublishPort=100.64.0.12:8081:8081
    ```

    or `127.0.0.1`, for a monitor on the VM itself:

    ```ini
    PublishPort=127.0.0.1:8081:8081
    ```

    Never publish it without an address (`8081:8081`): that opens it on every interface of the
    VM. The body holds no personal data, but there is no reason to show it to anyone.

2. Reload and restart the pod (both containers restart):

    ```bash
    systemctl --user daemon-reload && systemctl --user restart odin-pod
    ```

3. Check it from a machine that should reach it:

    ```bash
    curl -i http://100.64.0.12:8081/health
    ```

    The first line is `HTTP/1.1 200 OK` while ODIN is up.

## Add an Uptime Kuma monitor

1. In Uptime Kuma, **Add New Monitor**.
2. **Monitor Type**: *HTTP(s)*. Or, to look at the body as well, *HTTP(s) - Json Query*, with
   the query `status` and the expected value `up`.
3. **URL**: `http://100.64.0.12:8081/health` (your published address).
4. **Heartbeat Interval**: 60 s. **Retries**: 2 or 3, so a restart (ODIN is `starting` for a few
   seconds, longer after an update) does not alert.
5. **Accepted Status Codes**: `200-299` (the default). ODIN answers `503` when it is down.
6. Pick a notification that does **not** go through ODIN's Signal API — ntfy, e-mail, another
   messenger. A Signal notification would need the same `signal-api` container that may be the
   reason ODIN is down.

When the monitor goes down, the reasons in its message (or `podman exec odin odin health`) say
what is wrong; [Troubleshoot](troubleshoot.md) covers the usual causes.

## Turn the endpoint off

Set `ODIN_HEALTH_PORT=0` in `~/odin/odin.env` and remove the `HealthCmd=` and `Notify=healthy`
lines from `~/.config/containers/systemd/odin.container` (without the endpoint, the check never
passes and the unit never counts as started). Then:

```bash
systemctl --user daemon-reload && systemctl --user restart odin
```
