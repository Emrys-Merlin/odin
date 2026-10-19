# ODIN — Open Dinner Invitation Notifier

ODIN is a Signal bot that organises the weekly open Sunday dinner at our flat share. This repo is
`odin` (called `odib` until v0.3.0); the bot's Signal display name is **Odin 🍽️**.

Work is tracked in GitHub issues (milestone **MVP** for the first usable version). This document
holds the goals and the agreed design; issues hold the individual tasks.

## The problem

Every Sunday evening people can come to our flat share and have dinner together. Two questions
need answering each week:

1. **Does dinner take place?** Sometimes nobody from the flat is home — then guests must be told
   it is cancelled.
2. **How much food do we need?** If dinner happens, we need a rough head count by Friday afternoon
   to order food.

## Setup

ODIN is a member of two Signal groups:

- **Flat group** — the flatmates. Decides whether dinner happens.
- **Dinner group** — everyone invited (all flatmates are in it too). Receives the announcement.

## Weekly cycle (MVP)

All times are configurable; defaults below, timezone `Europe/Berlin`.

| When (default) | Group  | Action |
|----------------|--------|--------|
| Tue 18:00      | flat   | Ask whether dinner takes place this Sunday; react 👍 to confirm. Deadline: Wed 18:00. |
| Wed 12:00      | flat   | *Nudge* — only if there is no 👍 yet: "nobody confirmed, dinner will be cancelled at 18:00". Can be disabled. |
| Wed 18:00      | dinner | **No 👍** → bilingual cancellation. **≥1 👍** → bilingual announcement + RSVP request (see below). |
| Fri 14:00      | flat   | Tally — only if dinner is on: number of 👍 reactions on the dinner announcement. |

The announcement asks guests to react 👍 if they are coming, **please by Fri 14:00** (we order
food then) — not a hard deadline, reactions after it are fine. It states two times: **17:00** for
anyone who wants to help cook (explicitly optional — helping is absolutely no requirement) and
**18:00** otherwise. Plus-ones are mentioned in a reply by the guest and counted by humans.

**Dinner weekday change:** when dinner moves to another weekday (`/settime dinner`), a week of the
new weekday whose steps would all lie before the switch (e.g. Sun → Mon: the Monday right after
the last Sunday dinner) is *dropped*. Nothing goes to the flat group for it, but the dinner group
gets the normal cancellation, once, as soon as the switch takes effect (with the new weekday's
name). Like any late action it is skipped after the dropped week's dinner start, or once the
catch-up grace counted from the switch has passed. The dropped week is stored in the state DB
when the switch is applied, so a restart neither loses nor repeats it.

The same holds when the dinner weekday is changed **in the config file** and ODIN is restarted.
ODIN stores the dinner the weeks run on. If the config file names another weekday while a dinner
week is running (anything of it already recorded), that week keeps its weekday, and the new one
takes over at its dinner, exactly like a chat change (logged as a warning at startup and at the
switch; `/schedule` and `/status` show it, `odin check-config` mentions it). Between weeks it
applies at once. A chat change wins over the config file, as every override does. After a switch,
every week that was started or dropped and is not finished yet is finished (late steps recorded as
skipped), so nothing stays open even if ODIN was down over the switch.

**Cancelling via chat:** `/cancel` in the flat group cancels the current dinner week (the one
whose dinner has not started yet) after a confirmation. ODIN replies with the cancellation it
would post and asks for the configured emoji on that reply; the reply is tracked like the flat
poll. As soon as anyone in the flat group reacts with it (the requester too), ODIN posts the
normal bilingual cancellation template to the dinner group on its next tick and records it as the
week's cancellation, so the dinner group never gets two. Before the flat deadline it replaces the
decision (an open flat ask or nudge is skipped); after an announcement it follows it, and an open
tally is skipped. A request that nobody confirms does nothing; it lapses when the week's dinner
starts. `/cancel` is refused once the cancellation went out (or was skipped as too late), for a
week dropped by a dinner weekday change, and while a request of this week is open.

### Reaction rules

- A 👍 (configurable emoji) from **anyone** in the flat group counts. No member list.
- Removing a reaction before the deadline withdraws it (this covers "reacted by mistake").
- Reactions after the deadline, and other emojis, are ignored.
- The tally counts the configured emoji on the dinner announcement at tally time.
- A `/cancel` request is confirmed by the configured emoji on ODIN's reply, from anyone in the
  flat group, until the week's dinner starts; removing it before ODIN's next tick withdraws it.

### Robustness

- State lives in SQLite. Every action is recorded once sent; **nothing is ever posted twice**.
  The one exception: a send that times out while waiting for Signal's answer is retried, though
  it may have gone out (at least once rather than at most once — a missing cancellation is worse
  than a duplicate). A send that Signal accepted is recorded even if its answer can't be read.
- The scheduler is a *reconcile loop*: on every tick it computes what should have happened by now
  from config + state, and does what is missing. Restarts and missed ticks are therefore safe.
- **Catch-up:** an action that is late (bot was down) is still performed while within a grace
  window — by default until dinner starts — and skipped after that.

## Language

- Dinner group: **bilingual**, German first, then English, in one message.
- Flat group: German.
- The messages of the weekly cycle are templates in the config (placeholders like `{deadline}`,
  `{cook_time}`).
- Chat-command replies are German UI strings in code, not config templates.

## Chat commands

Flatmates can look at and change ODIN's settings from the chat with commands. A command is a
message that starts with `/` or `!` followed by the command name (`/help` = `!help`; the name is
case-insensitive). Command names and their arguments are English only (`/nudge on`, weekdays as
`thu`), never mixed with German; replies are in German. A message that starts with `/` or `!` plus
a letter but is no known command gets a short German error pointing to `/help`; everything else
is ignored. Commands are answered in the flat group only; in the dinner group (or any other
group) ODIN ignores them.

| Command | What it does |
|---------|--------------|
| `/help` | Lists all commands with a one-line description. |
| `/status` | This dinner week: each step (flat ask, nudge, decision, tally) as sent, skipped or pending, the 👍 counts on the flat poll and the announcement, a cancellation via `/cancel` (also after the announcement) or an open `/cancel` request, a pending dinner weekday change, and the next action. |
| `/schedule` | Shows the 7 schedule points (key, German description, weekday and time), whether the nudge is off, and who changed a value via chat. |
| `/texts` | Lists the five editable weekly templates: group, short description, and who changed it when if overridden. |
| `/text <name>` | Shows a template twice: raw as a ready-to-send `/settext <name>` command, and rendered with this week's values (for `tally` with the current 👍 count, or a sample count of 3). |
| `/settext <name>` | Replaces template `<name>` (`flat_ask`, `nudge`, `announcement`, `cancellation`, `tally`) with the text on the following lines, after checking its placeholders; replies with a preview. |
| `/resettext <name>` | Drops the chat change to template `<name>`, back to the config file's text; replies with a preview. |
| `/vars [name]` | Lists the template placeholders with a German description and current value; with a template name only those allowed in it. |
| `/settime <point> <weekday> <HH:MM>` | Moves a schedule point (`flat_ask`, `nudge`, `flat_deadline`, `rsvp_by`, `tally`, `cook`, `dinner`); weekdays as in the config (`thu`, `thursday`). Takes effect at once, but is rejected if it breaks the schedule order, moves the current dinner week, or makes a not-yet-done step of this week due right now. |
| `/settime dinner <weekday> <HH:MM>` (other weekday) | Moves dinner to another weekday. Never touches the running dinner week: once it has started (flat ask due or anything recorded) the change waits until that week's dinner, else it applies at once. A week of the new weekday whose steps would all lie before the switch (e.g. Sun → Mon) is dropped — no dinner, nothing sent to the flat group, but ODIN posts the cancellation for it to the dinner group when the switch takes effect; the reply names the first new dinner, warns about a dropped one and says when its cancellation goes out. `/schedule` and `/status` show a pending change; a new time on the current weekday or `/resettime dinner` discards it. |
| `/nudge on\|off` | Turns the nudge on or off; same guard. |
| `/resettime <point>` | Drops the chat change of a point back to the config value (for `nudge` also on/off); same guard. For `dinner` it first discards a pending weekday change; going back to the config's weekday waits like `/settime dinner`. |
| `/cancel` | Cancels this week's dinner after a confirmation: ODIN shows the cancellation and asks for a 👍 on its reply; once someone reacts, the dinner group gets the cancellation (once, also after an announcement). See *Cancelling via chat*. |
| `/version` | Shows the running version of ODIN (the same as `odin --version`, from the release tag). |

## Architecture

- **Python 3.14** package managed with **uv** (src layout, package `odin`).
- Signal access via **`bbernhard/signal-cli-rest-api`** in `json-rpc` mode, running as a sidecar
  container. ODIN talks to it over HTTP + WebSocket with a thin own client behind an interface; a
  **fake client** implements the same interface for tests.
- Time is injected (clock interface), so the weekly cycle is tested by time travel, fully offline.
- **Config:** TOML file mounted into the container (schedule, emoji, templates). **Env vars** for
  deployment-specific values: `SIGNAL_NUMBER`, signal API URL. The group IDs are chosen in
  `odin setup` and stored in the SQLite state DB; `FLAT_GROUP_ID` / `DINNER_GROUP_ID` env vars
  override them when set. Until ODIN is set up, `odin run` waits instead of failing.
- **Quality gates:** ruff (lint + format), ty (types), pytest. ruff and ty run as **prek** hooks;
  CI runs `prek run --all-files` and pytest on every PR.

## Deployment

- Every merge to `main` is a semver release: CI tags `vX.Y.Z` (bump from the PR's `release:*`
  label, see `CLAUDE.md`), creates a GitHub Release and pushes the container image to **GHCR**
  (public package; it contains no secrets) as `X.Y.Z`, `X.Y`, `X`, `latest` and the commit SHA.
  `release:none` merges publish nothing. We stay on `0.x` until the bot goes live; going live is a
  `release:major` PR → `1.0.0`.
- Homelab: a **Debian 13 VM on Proxmox** (general container VM, ~1 vCPU / 1.5 GB RAM / 10 GB),
  **rootless podman** under a dedicated `odin` user with lingering, **Quadlet** units defining a pod
  (signal-cli-rest-api + odin), **`podman auto-update`** to follow the GHCR image. The Quadlet
  unit follows the **major tag** (`ghcr.io/emrys-merlin/odin:0` now, `:1` after going live), not
  `:latest`, so auto-update never pulls a breaking release on its own; a major bump means editing
  the unit by hand.
- The signal-cli data volume holds the account keys — **it must be backed up** (Proxmox VM backup
  covers it). Losing it means re-registering the number.

### Secrets and variables

| Name | What | Where it comes from |
|------|------|---------------------|
| `SIGNAL_NUMBER` | Bot phone number, E.164 (`+49…`) | Tim |
| group IDs (flat, dinner) | Base64 Signal group IDs | Picked in `odin setup` after ODIN is added to both groups; stored in the state DB. Optional override: `FLAT_GROUP_ID`, `DINNER_GROUP_ID` env vars |
| signal-cli data volume | Account keys | Created at registration |
| captcha token | One-time, for registration | signalcaptchas.org |

No API tokens are needed: the GHCR image is public, and the Signal API container is only reachable
inside the pod.

## Development process

- One GitHub issue per vertical slice; each issue is self-contained so a cold Claude Code cloud
  session can pick it up.
- Changes land via PRs that Tim reviews; CI must be green.
- Cloud sessions have no secrets and cannot reach Signal — everything is testable offline.

## Non-goals for the MVP

Tracked as separate issues where useful:

- Cancelling a dinner in advance for a later week, or taking a `/cancel` back once it went out.
- Skip dates / holiday calendar (#12).
- Counting plus-ones automatically (#13); guest names or lists.
- More than one dinner per week; reminders to guests.
