# Change the config

**How-to guide** — steps for one task you already know you want to do.

Edit the config file, check it, and restart ODIN.

Commands on the machine run as the `odin` user (`sudo machinectl shell odin@`). Every key is listed in
[Configuration](../../reference/configuration.md), the placeholders of the texts in
[Templates](../../reference/templates.md).

!!! tip "Small changes work from the chat"

    Flatmates can change times and texts without touching the file:
    [Edit a text](../chat/edit-a-text.md), [Move dinner to another day](../chat/move-dinner-day.md),
    [Pause the nudge](../chat/pause-nudge.md).

## Edit and apply

1. Edit the file:

    ```bash
    nano ~/odin/config/config.toml
    ```

2. Check it. The container sees the edited file right away (it is mounted read-only), so this
   checks the new version before ODIN uses it:

    ```bash
    podman exec odin odin check-config
    ```

    It prints `Config OK: /config/config.toml` and the next scheduled actions. An error names the
    bad value; fix it and check again.

3. Restart the bot:

    ```bash
    systemctl --user restart odin
    journalctl --user -u odin -e
    ```

    If the config is still broken, the error shows in the log and the unit restarts every 10 s
    until it is fixed.

## A value does not change after the restart

A value changed from the chat wins over the config file. `/schedule` and `/texts` in the flat
group show who changed what. To fall back to the file's value, send `/resettime <point>` or
`/resettext <name>` in the flat group ([Chat commands](../../reference/chat-commands.md)).

## Change the dinner weekday in the file

1. Change the dinner weekday in `config.toml` as above and check it. If a dinner week is already
   running, `check-config` says so:

    ```text
    Dinner weekday change pending: sun 18:00 → mon 18:00. …
    ```

2. Restart the bot. The log warns about the pending change at startup.

The running week keeps its weekday and the new one takes over at that week's dinner; between
weeks it applies at once. `/schedule` and `/status` in the flat group show the pending change.
What happens to the weeks around the switch:
[Changing the dinner weekday](../../explanation/weekday-change.md).

## Change the profile name or picture

Edit the `[profile]` section (a picture goes next to the config file, e.g.
`~/odin/config/odin.png`, with `avatar = "odin.png"`), then apply it to Signal:

```bash
podman exec -it odin odin setup
```

On a finished setup this only re-applies the profile.

## Change `odin.env`

Edit `~/odin/odin.env`, then `systemctl --user restart odin`. Do not set `SIGNAL_API_URL` there:
the default `http://localhost:8080` is the Signal API inside the pod.

## Take over a new example config

When a release notes a config change, compare the example with yours and copy over what is new:

```bash
git -C ~/odin-src pull
diff ~/odin-src/config.example.toml ~/odin/config/config.toml
```
