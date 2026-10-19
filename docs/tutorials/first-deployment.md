# First deployment

**Tutorial** — a guided lesson: follow along and learn by doing.

In this tutorial we take a fresh Debian machine to a running ODIN: we run ODIN on it with
podman, give it its own Signal account, add it to the flat group and the dinner group, and
finally watch it ask the flat group whether dinner takes place.

You do not need to know podman. Every step says what to type and what you should see.

Allow about an hour: half of it for the machine and the containers, 20 minutes for the Signal
account.

## What you need

- A **Debian 13 machine** that runs all the time, with internet access. A small VM or a home
  server is ideal; ODIN needs about 1 CPU core, 1.5 GB of memory and 10 GB of disk. We assume a
  fresh install with an SSH server and a user with `sudo` rights; we call that user `tim` here.
- A **SIM card for ODIN's own phone number**, in any phone, to receive one verification code.
- **Your own phone with Signal**, already in the flat group and the dinner group.
- A **desktop browser** and your **password manager**.

## What we are building

At the end, the machine runs two containers side by side in a *pod*: the Signal API
([signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)), which holds ODIN's
Signal account, and ODIN itself, which talks to it. A few things about podman make the commands
below easier to follow:

- **Rootless.** The containers run as an ordinary Linux user, `odin`, not as root.
- **Quadlet.** We do not type long `podman run` commands. We copy a few short unit files
  (`odin.pod`, `odin.container`, …) into `odin`'s config directory, and systemd turns them into
  services. So we start and stop ODIN with `systemctl --user`, and read its logs with
  `journalctl --user`.
- **Lingering.** `odin`'s own systemd normally runs only while `odin` is logged in. Lingering
  starts it at boot, so ODIN runs without anyone logged in.
- **Volumes.** ODIN's data lives in two volumes that outlive the containers: `odin-signal`
  (the Signal account's keys) and `odin-data` (ODIN's database).

The units, volumes and image tags are listed in the
[deployment units reference](../reference/deployment-units.md); the
[architecture](../explanation/architecture.md) explains why it is built this way.

## 1. Install podman

Log in to the machine over SSH and bring it up to date:

```bash
ssh tim@<machine>
sudo apt update && sudo apt full-upgrade -y
```

The upgrade ends without errors and you are back at the prompt, e.g. `tim@odin:~$`. Now install
podman and a few helpers:

```bash
sudo apt install -y podman systemd-container dbus-user-session git
podman --version
```

The last command prints `podman version 5.…`.

## 2. Create the `odin` user

Create the user that will run ODIN. Nobody logs in as it with a password:

```bash
sudo adduser --disabled-password --comment "ODIN bot" odin
grep odin /etc/subuid /etc/subgid
```

`grep` prints one line per file, e.g.:

```text
/etc/subuid:odin:100000:65536
/etc/subgid:odin:100000:65536
```

These are the user IDs that `odin`'s containers may use. Next, turn on lingering for `odin`, so
its services start at boot:

```bash
sudo loginctl enable-linger odin
```

Now we **become `odin`**. We use `machinectl`, because it opens a real login session for `odin`,
which `systemctl --user` needs:

```bash
sudo machinectl shell odin@
```

The prompt changes to `odin@…:~$`. **Every command from here on runs in this shell, as
`odin`**, unless we say otherwise. Check that it works:

```bash
systemctl --user status
podman info --format '{{.Host.Security.Rootless}}'
```

The first command shows `State: running` near the top (press ++q++ to leave it), the second
prints `true`.

## 3. Install the files

We take the unit files and the example config from ODIN's repository:

```bash
git clone https://github.com/Emrys-Merlin/odin.git ~/odin-src
mkdir -p ~/.config/containers/systemd ~/odin/config
cp ~/odin-src/deploy/quadlet/*.pod ~/odin-src/deploy/quadlet/*.container \
   ~/odin-src/deploy/quadlet/*.volume ~/.config/containers/systemd/
cp ~/odin-src/deploy/quadlet/odin.env.example ~/odin/odin.env
cp ~/odin-src/config.example.toml ~/odin/config/config.toml
chmod 600 ~/odin/odin.env
ls ~/.config/containers/systemd
```

`ls` lists five files:

```text
odin-data.volume  odin-signal.volume  odin.container  odin.pod  signal-api.container
```

Now tell ODIN its phone number. Open the env file:

```bash
nano ~/odin/odin.env
```

Replace `+49XXXXXXXXXXX` in the line `SIGNAL_NUMBER=` with ODIN's number, in international
format without spaces (e.g. `SIGNAL_NUMBER=+4915112345678`). Leave everything else as it is.
Save with ++ctrl+o++, ++enter++ and leave with ++ctrl+x++.

We keep `config.toml` as it is: its defaults are the usual week (ask on Tuesday 18:00, dinner on
Sunday 18:00). Everything in it is described in the
[configuration reference](../reference/configuration.md); you can change it later
([Change the config](../how-to/operate/change-config.md)).

Let ODIN check the config before we start anything. This downloads ODIN's image the first time,
which takes a moment:

```bash
podman run --rm --env-file ~/odin/odin.env -v ~/odin/config:/config:ro \
  ghcr.io/emrys-merlin/odin:0 check-config
```

It ends like this (with your number and this week's dates):

```text
Config OK: /config/config.toml
Number:       +4915112345678
Flat group:   -
Dinner group: -
…
Not set up yet (no flat and no dinner group chosen) — run: podman exec -it odin odin setup

Next scheduled actions:
  Tue 2026-10-20 18:00  flat ask (flat group)
  Wed 2026-10-21 12:00  nudge (flat group, only if nobody confirmed)
  Wed 2026-10-21 18:00  announcement / cancellation (dinner group)
  Fri 2026-10-23 14:00  tally (flat group, only if dinner is on)
```

*Not set up yet* is expected: we have not given ODIN a Signal account or groups yet.

## 4. Start ODIN

Let systemd read the unit files, then start the pod:

```bash
systemctl --user daemon-reload
systemctl --user start odin-pod
```

The start downloads the Signal API's image and can take a minute or two. Then look at what is
running:

```bash
podman ps
```

There are three containers, all `Up`: `odin-pod-infra` (it holds the pod together),
`signal-api` and `odin`.

Now follow ODIN's log:

```bash
journalctl --user -u odin -f
```

While the Signal API starts (10–30 seconds), ODIN logs that the API is not reachable yet. Then
it says:

```text
ODIN is not set up yet (…) — run: podman exec -it odin odin setup
```

That is what we want to see: ODIN runs and waits for its setup. Press ++ctrl+c++ to stop
following the log; ODIN keeps running.

Let us make sure it also comes back after a reboot. Leave the `odin` shell with `exit`, then, as
`tim`:

```bash
sudo reboot
```

Wait a minute, log in again with `ssh tim@<machine>`, and become `odin` again:

```bash
sudo machinectl shell odin@
podman ps
```

The same three containers are `Up` again, without us starting anything.

## 5. Turn on automatic updates

ODIN and the Signal API get updates through `podman auto-update`. A timer runs it daily:

```bash
systemctl --user enable --now podman-auto-update.timer
systemctl --user list-timers
```

The list contains `podman-auto-update.timer` with its next run, around midnight. From now on new
ODIN releases arrive by themselves; see [Upgrade](../how-to/operate/upgrade.md) for what that
covers.

## 6. Set up ODIN's Signal account

Now ODIN gets its own Signal account and joins the two groups. One command walks us through it:

```bash
podman exec -it odin odin setup
```

The wizard goes through steps 0 to 9 and announces each one, e.g. `── Step 1/9 · Captcha`. If
anything interrupts it, run the same command again: it continues where it stopped.

**Step 0 · Preflight** checks the Signal API and says `+49… is not registered yet.`

**Step 1 · Captcha.** Signal wants a captcha for every new account.

1. Open <https://signalcaptchas.org/registration/generate.html> in your desktop browser and
   solve the captcha.
2. The page shows an **Open Signal** link. Right-click it → *Copy link*.
3. Paste it at `Captcha link:` right away — it expires within a minute or two.

**Step 2 · Register.** Signal sends a code to ODIN's SIM. The wizard says:

```text
✓ Signal is sending a verification code by SMS to the SIM's phone.
```

(If Signal cannot send an SMS, it counts down a minute, asks for a fresh captcha and calls the
SIM's phone instead.)

**Step 3 · Code.** Type the 6-digit code from the SMS at `Code, e.g. 123-456`. The wizard
answers `✓ +49… is registered.` ODIN now has a Signal account.

**Step 4 · PIN.** The wizard shows a registration lock PIN, once. It stops anyone else from
taking over ODIN's number.

1. In your password manager, create an entry **ODIN Signal registration lock PIN** with ODIN's
   number, and paste the PIN there.
2. Type its last 4 characters to confirm.

The wizard says `✓ PIN set.` ODIN never needs the PIN in daily operation.

**Step 5 · Profile** sets ODIN's name, `✓ Profile name set to Odin 🍽️.` Nothing to answer.

**Step 6 · Hello.** Before you can add ODIN to a group as a full member, ODIN needs to have
heard from you. At `Your own Signal number`, type your number (`+4917…`). ODIN writes to you:

<div class="chat" data-group="Odin 🍽️" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Hallo, hier ist Odin 🍽️! Bitte antworte kurz auf diese Nachricht, damit die Einrichtung
weitergehen kann.
</div>
<div class="msg me" markdown>
👋
</div>
</div>

On your phone, open the message request from Odin 🍽️, tap **Accept**, and reply with anything.
The wizard says `✓ Got your reply.`

**Step 7 · Groups.** On your phone, open the **flat group** → group settings → *Add members* →
Odin 🍽️. Do the same in the **dinner group**. The wizard watches and lists the groups as ODIN
joins them, e.g.:

```text
Groups ODIN sees:
  1. Sonntagsessen — member
  2. WG — member
```

When it asks `Are both groups listed as member?`, press ++enter++. Then type the number of the
flat group (here `2`) and of the dinner group (here `1`). The wizard says
`✓ Flat group: WG. Dinner group: Sonntagsessen.`

**Step 8 · Test.** At `Post a test message to the flat group now? [y/N]`, type `y`. On your
phone, the flat group shows:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Hallo, ich bin Odin 🍽️! Ab jetzt frage ich jeden Dienstag, ob am Sonntag das offene
Abendessen stattfindet. Bestätigt wird mit 👍.
</div>
</div>

**Step 9 · Done** shows ODIN's number, yours and both groups, and ends with:

```text
✓ ODIN is set up. A running `odin run` notices within 30 s and starts — no restart needed.
```

There is nothing to restart: ODIN, which has been waiting since step 4, starts by itself.

!!! note "Finished between Tuesday 18:00 and Wednesday 18:00?"

    Then ODIN posts this week's question to the flat group within a minute: it was due on
    Tuesday, and ODIN catches up on it. That is the real question for this Sunday.

The wizard's options, e.g. to redo a step later, are in the [CLI reference](../reference/cli.md).

## 7. Check the setup

Ask ODIN for a summary:

```bash
podman exec odin odin setup --status
```

The lines for the Signal API, `Registered`, `PIN set`, `Profile applied`, `Hello`, `Flat group`
and `Dinner group` (each with the group's name) all start with ✓. The last line reads:

```text
ODIN is set up.
```

## 8. Keep a backup

ODIN's Signal keys now live in the volume `odin-signal`. If they are lost, the number has to be
registered again, which needs the SIM. So we recommend backing them up, and the simplest way is
to back up the whole machine regularly. If it is a VM, your hypervisor probably has this built
in: on Proxmox VE, for example, a backup job under *Datacenter* → *Backup* covers it.

To have one copy right away, export the volume:

```bash
podman volume export odin-signal --output ~/odin-signal-$(date +%F).tar
ls -lh ~/odin-signal-*.tar
```

`ls` lists the tarball. Move it somewhere safe, off this machine.

!!! warning "The backups contain ODIN's private keys"

    Keep them as private as your password manager: encrypted, and never in a repository.

How to restore, and what else is worth backing up:
[Back up and restore](../how-to/operate/backup-restore.md).

## 9. See ODIN at work

The deployment is done. Let us see ODIN answer in the flat group. On your phone, write in the
flat group:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 25.10.<br>
⏳ Frage an die WG: Di 18:00<br>
⏳ Erinnerung: Mi 12:00<br>
⏳ Entscheidung: Mi 18:00<br>
⏳ Zählung: Fr 14:00<br>
Nächste Aktion: Frage an die WG, Di 18:00
</div>
</div>

ODIN answers within a few seconds with the dinner week it is working on and what it does next:
here, it asks the flat group on Tuesday at 18:00. Your dates depend on the day. (If the week's
question is already past, the steps show ⏭️ *übersprungen*, and ODIN starts with next week's.)

We do not have to wait until Tuesday to see the question. If the question for this week is still
to come (between Sunday's dinner and Tuesday 18:00), we can move it a few minutes ahead. Say it
is Monday, 20:00; we write today's weekday and a time ten minutes from now:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime flat_ask mon 20:10`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Frage an die WG (flat_ask): Mo 20:10, nächstes Mal Mo 19.10. um 20:10<br>
Das gilt schon für diese Woche.
</div>
</div>

At 20:10, within a minute, ODIN asks:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Findet am Sonntag das offene Abendessen statt? 🍽️
Wer da ist und das Abendessen ausrichtet, reagiert bitte bis Mittwoch 18:00 mit 👍 auf diese
Nachricht. Ein 👍 reicht – ohne 👍 sage ich das Abendessen am Mittwoch um 18:00 ab.
</div>
</div>

This is the real question for this Sunday, just earlier than usual: the flatmates answer it with
👍 as they would on Tuesday, and the rest of the week runs as normal. Now we put the question back
on Tuesday for the following weeks:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/resettime flat_ask`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgesetzt ✅ (wieder wie in der Config)<br>
Frage an die WG (flat_ask): Di 18:00, nächstes Mal Di 27.10. um 18:00<br>
Das gilt ab nächster Woche.
</div>
</div>

On any other day, ODIN refuses the `/settime` with a short German explanation and changes
nothing. Then the first question simply comes on Tuesday at 18:00.

## What we did

We ran ODIN and the Signal API on a Debian machine as rootless podman containers that start at
boot and update themselves, gave ODIN its own Signal account protected by a PIN, added it to the
flat group and the dinner group, made a backup of its keys, and watched it answer in the chat.

## Next steps

- Show the flatmates [their first week with ODIN](first-week.md).
- Everyday operation: [upgrade](../how-to/operate/upgrade.md),
  [roll back](../how-to/operate/rollback.md),
  [change the config](../how-to/operate/change-config.md), and
  [troubleshoot](../how-to/operate/troubleshoot.md) when something does not work.
- All chat commands: [chat commands reference](../reference/chat-commands.md).
- How a dinner week runs: [the weekly cycle](../explanation/weekly-cycle.md).
