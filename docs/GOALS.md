# ODIN — Open Dinner Invitation Notifier

ODIN is a Signal bot that organises the weekly open Sunday dinner at our flat share. This repo is
`odib`; the bot's Signal display name is **Odin 🍽️**.

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

### Reaction rules

- A 👍 (configurable emoji) from **anyone** in the flat group counts. No member list.
- Removing a reaction before the deadline withdraws it (this covers "reacted by mistake").
- Reactions after the deadline, and other emojis, are ignored.
- The tally counts the configured emoji on the dinner announcement at tally time.

### Robustness

- State lives in SQLite. Every action is recorded once sent; **nothing is ever posted twice**.
- The scheduler is a *reconcile loop*: on every tick it computes what should have happened by now
  from config + state, and does what is missing. Restarts and missed ticks are therefore safe.
- **Catch-up:** an action that is late (bot was down) is still performed while within a grace
  window — by default until dinner starts — and skipped after that.

## Language

- Dinner group: **bilingual**, German first, then English, in one message.
- Flat group: German.
- All message texts are templates in the config (placeholders like `{deadline}`, `{cook_time}`).

## Architecture

- **Python 3.14** package managed with **uv** (src layout, package `odib`).
- Signal access via **`bbernhard/signal-cli-rest-api`** in `json-rpc` mode, running as a sidecar
  container. ODIN talks to it over HTTP + WebSocket with a thin own client behind an interface; a
  **fake client** implements the same interface for tests.
- Time is injected (clock interface), so the weekly cycle is tested by time travel, fully offline.
- **Config:** TOML file mounted into the container (schedule, emoji, templates). **Env vars** for
  deployment-specific values: `SIGNAL_NUMBER`, signal API URL. The group IDs are chosen in
  `odib setup` and stored in the SQLite state DB; `FLAT_GROUP_ID` / `DINNER_GROUP_ID` env vars
  override them when set. Until ODIN is set up, `odib run` waits instead of failing.
- **Quality gates:** ruff (lint + format), ty (types), pytest. ruff and ty run as **prek** hooks;
  CI runs `prek run --all-files` and pytest on every PR.

## Deployment

- Every merge to `main` is a semver release: CI tags `vX.Y.Z` (bump from the PR's `release:*`
  label, see `CLAUDE.md`), creates a GitHub Release and pushes the container image to **GHCR**
  (public package; it contains no secrets) as `X.Y.Z`, `X.Y`, `X`, `latest` and the commit SHA.
  `release:none` merges publish nothing. We stay on `0.x` until the bot goes live; going live is a
  `release:major` PR → `1.0.0`.
- Homelab: a **Debian 13 VM on Proxmox** (general container VM, ~1 vCPU / 1.5 GB RAM / 10 GB),
  **rootless podman** under a dedicated `odib` user with lingering, **Quadlet** units defining a pod
  (signal-cli-rest-api + odib), **`podman auto-update`** to follow the GHCR image. The Quadlet
  unit follows the **major tag** (`ghcr.io/emrys-merlin/odib:0` now, `:1` after going live), not
  `:latest`, so auto-update never pulls a breaking release on its own; a major bump means editing
  the unit by hand.
- The signal-cli data volume holds the account keys — **it must be backed up** (Proxmox VM backup
  covers it). Losing it means re-registering the number.

### Secrets and variables

| Name | What | Where it comes from |
|------|------|---------------------|
| `SIGNAL_NUMBER` | Bot phone number, E.164 (`+49…`) | Tim |
| group IDs (flat, dinner) | Base64 Signal group IDs | Picked in `odib setup` after ODIN is added to both groups; stored in the state DB. Optional override: `FLAT_GROUP_ID`, `DINNER_GROUP_ID` env vars |
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

- Chat commands (`!cancel`, `!status`) and changing config via chat.
- Skip dates / holiday calendar.
- Counting plus-ones automatically; guest names or lists.
- More than one dinner per week; reminders to guests.
