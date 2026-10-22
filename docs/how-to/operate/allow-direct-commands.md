# Allow commands in a direct message

**How-to guide** — steps for one task you already know you want to do.

Let some people send chat commands to ODIN in a 1:1 chat, so a `/status` or `/settext` round trip
does not fill the flat group.

Anyone can message ODIN's number, guests included, so only the people on a list get an answer.
The keys are in [Configuration](../../reference/configuration.md#commands), what works in a direct
message in [Chat commands](../../reference/chat-commands.md#direct-messages).

!!! note "Assumed setup"

    Commands run as the `odin` user (`sudo machinectl shell odin@`), with files where
    [First deployment](../../tutorials/first-deployment.md) puts them: see
    [Host layout](../../reference/deployment-units.md#host-layout). Adjust the paths if your
    setup differs.

## Find the person's ID

An entry is a phone number in E.164 format (`+4915…`, no spaces) or a Signal UUID. Signal does
not always show a sender's number to ODIN, so the safe way is to take the ID from ODIN's log:

1. The person sends ODIN any direct message, e.g. `/help`. They get no answer yet.
2. Look for the line ODIN logged for it:

    ```bash
    journalctl --user -u odin --since "10 min ago" | grep "ignoring a direct message"
    ```

    ```text
    … INFO odin.events: ignoring a direct message from +4915100000001 (UUID 5c6a3e2b-1f0d-4c8e-9a7b-2d3e4f5a6b7c): not in commands.direct_senders
    ```

    If the number is hidden, the line shows the UUID in both places. Either ID works; the UUID
    keeps matching if the person changes their number.

## Add them and choose the notice

1. Edit the config file:

    ```bash
    nano ~/odin/config/config.toml
    ```

2. In the `[commands]` table, add the ID to `direct_senders`, and decide on `direct_notice`:

    ```toml
    [commands]
    direct_senders = ["+4915100000001"]
    direct_notice = true
    ```

    With `direct_notice = true` (the default) the flat group gets one line whenever a command
    from a direct message changed something, so the others still see every change. Set it to
    `false` if the flat trusts the people on the list; then a direct command posts nothing to
    the flat group at all.

3. Check the file and restart the bot, as in [Change the config](change-config.md):

    ```bash
    podman exec odin odin check-config
    systemctl --user restart odin
    ```

    `check-config` shows `DM commands:  1 allowed sender(s), notice to the flat group on`. A
    malformed entry is an error naming `commands.direct_senders`.

## What it looks like

The person sends a command to ODIN directly and gets the reply there:

<div class="chat" data-group="Odin 🍽️" markdown>
<div class="msg me" markdown>
`/settime tally fri 15:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅
Zählung der Gäste (tally): Fr 15:00, nächstes Mal Fr 09.10. um 15:00
Das gilt schon für diese Woche.
</div>
</div>

With the notice on, the flat group gets one line instead of command and reply:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
✏️ Tim hat per Direktnachricht geändert: /settime tally fri 15:00
</div>
</div>

`/cancel`, `/introduce` and `/hiatus` need a confirmation by reaction in the flat group, so they
are refused in a direct message:

<div class="chat" data-group="Odin 🍽️" markdown>
<div class="msg me" markdown>
`/cancel`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
/cancel geht nur in der WG-Gruppe: Dort bestätigt es jemand mit 👍, und alle sehen es.
</div>
</div>

A message that is not a command gets a hint: `Hier verstehe ich nur Befehle – /help zeigt sie.`

## Remove someone

Delete their entry from `direct_senders`, check and restart as above. From then on their direct
messages get no answer again.
