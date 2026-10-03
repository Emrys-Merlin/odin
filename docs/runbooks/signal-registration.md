# Runbook: set up ODIN's Signal account with `odib setup`

One-time setup, done by Tim. At the end:

- ODIN's number is registered as a **primary** Signal device, with a registration lock PIN and
  the profile name from the config (**Odin 🍽️**),
- ODIN is a full member of the flat group and the dinner group,
- the two group IDs are stored in ODIN's database — nothing to copy into env files.

Allow 20 minutes.

## Prerequisites

- The **SIM card for ODIN's number** in a phone, to receive the verification code (SMS or call).
- **Your own phone with Signal**, which is in both groups.
- A **desktop browser**, for the captcha.
- Your **password manager**, for the PIN.
- The **deployment is running** (deploy runbook `docs/runbooks/deploy.md`, #10): the pod with
  the Signal API and the `odib` container. `odib.env` only needs `SIGNAL_NUMBER` (E.164: `+49…`,
  no spaces). Until setup is done, `odib run` waits and logs
  `ODIN is not set up yet (…) — run: podman exec -it odib odib setup`; that is expected, not a
  crash.

## Background

- ODIN talks to Signal through
  [`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api) (json-rpc
  mode), a REST wrapper around [signal-cli](https://github.com/AsamK/signal-cli). `odib setup`
  drives that API for you; no curl, no setup container.
- Everything that makes ODIN *be* ODIN — identity keys, account password, group memberships —
  lives in the Signal API container's data volume. **Losing that volume means registering again,
  which needs the SIM.** See [Backing up the volume](#backing-up-the-volume--mandatory).
- We register a regular SIM number. The provider may recycle it one day, so the account must not
  depend on it: the **registration lock PIN** stops anyone else from registering the number while
  ODIN is active, and the **volume backup** means we never need to register again. See
  [Residual risk](#residual-risk-and-the-sim).

## The one command

As the `odib` user on the VM:

```bash
podman exec -it odib odib setup
```

The wizard goes through steps 0–9 and prints `── Step n/9 · …` for each. **You can stop it at any
point (Ctrl-C) and run the same command again** — every step first checks the real state and is
skipped when it is done, so it continues where it stopped. While the wizard runs, `odib run`
pauses (it sends nothing and ignores reactions); it resumes by itself within 30 s after the
wizard ends.

Only one wizard can run at a time. If a second one says *Another `odib setup` is running*, finish
the first; the lock of a killed wizard expires within 2 minutes.

## What each step asks

### Step 0 · Preflight

Checks that the Signal API is reachable and in json-rpc mode, and whether the number is
registered. If it is, steps 1–3 are skipped.

- *Cannot reach the Signal API* — the Signal API container is not running or still starting
  (it takes 10–30 s). Check `systemctl --user status odib-pod` and its logs (see
  [Troubleshooting](#troubleshooting)).
- *runs in '…' mode; ODIN needs MODE=json-rpc* — fix the Signal API container's environment.

### Step 1 · Captcha

Signal wants a captcha for every registration.

1. Open <https://signalcaptchas.org/registration/generate.html> in a desktop browser and solve
   it.
2. The page shows an **"Open Signal"** link. Right-click it → *Copy link*. (Alternatively: the
   browser's developer console has a line saying navigation to `signalcaptcha://signal-…` was
   prevented.)
3. Paste it at **`Captcha link:`** — with or without the `signalcaptcha://` prefix.

The token is only valid for a minute or two, so paste it right away. If Signal does not accept
it (*invalid or expired*), the wizard asks for a new one.

### Step 2 · Register (SMS or call)

The wizard asks Signal to send a code by **SMS**. Messages you may see:

- *Signal cannot send an SMS to this number; it will call instead.* — it counts down 60 s, then
  asks for a **fresh captcha** and requests a **voice call**. The call reads the code out.
- *Signal wants a minute between the SMS request and the call.* — same: countdown, fresh
  captcha.
- **Rate limit** — *Signal's rate limit was reached (too many registration attempts …)*. The
  wizard stops and says when the next attempt is possible (or "wait a few hours"). Run it again
  after that; nothing else to do.

On success: *✓ Signal is sending a verification code by SMS/call to the SIM's phone.*

### Step 3 · Code

Enter the 6-digit code at **`Code, e.g. 123-456`** — with or without the dash or a space.

- Code wrong → Signal rejects it; type it again.
- No code arrived → type **`new`**: back to step 1 with a new captcha.
- If you stopped the wizard after requesting a code, the next run says *A verification code was
  requested at …* and asks for it; press **Enter** (empty) to request a new one instead.
- **Registration lock** — *This number is still protected by the registration lock (PIN) of a
  previous Signal account.* A previous owner of the SIM number set a PIN. The lock expires
  7 days after that account was last active (Signal may say how many hours are left). There is
  nothing to do but wait and run `odib setup` again.

On success: *✓ +49… is registered.*

### Step 4 · PIN

The wizard generates a 16-character PIN (lower-case letters and digits without look-alikes) and
shows it **once**:

1. Create an entry **"ODIN Signal registration lock PIN"** in the password manager, with ODIN's
   number, and paste the PIN there. This is the only copy — Signal cannot recover it.
2. Type its **last 4 characters** to confirm you saved it.

Lost it before confirming? Ctrl-C and run `odib setup` again — you get a new PIN.

From now on, registering ODIN's number anywhere else requires this PIN, as long as ODIN has been
active within the last 7 days. ODIN itself never needs the PIN for day-to-day operation.

Want to choose the PIN yourself (at least 4 characters, entered twice, not shown)? Use
`odib setup --pin` — also to replace a PIN that is already set.

### Step 5 · Profile

Sets the profile name (and picture, if `avatar` is set) from the `[profile]` section of
`config.toml`. Runs on every wizard run, so a changed name or picture is applied by just running
`odib setup` again. Nothing to answer.

### Step 6 · Hello

Signal only lets someone add ODIN to a group as a **full member** if ODIN already has their
*profile key*, which it gets when they message it. Without this step ODIN would show up in the
groups as **"invited"** instead of as a member. So:

1. At **`Your own Signal number`**, enter your number in international format (`+4917…`). On a
   re-run your number from last time is the default; press Enter to keep it.
2. ODIN sends you the `hello` text from the config. On your phone: open the **message request**
   from Odin 🍽️, tap **Accept**, and **reply** with anything (e.g. 👋).
3. The wizard waits for the reply and says *✓ Got your reply.*

Optional: save ODIN as a contact on your phone — makes adding it to groups easier.

If you have hidden your number in Signal, your reply arrives without it; the wizard says so and
takes it as yours.

### Step 7 · Groups

On your phone, in the **flat group** and the **dinner group**: group settings → *Add members* →
Odin 🍽️ → add. (If a group only lets admins add members, an admin has to do it. ODIN does not
need to be an admin.)

The wizard lists the groups ODIN sees and updates the list by itself, e.g.

```text
Groups ODIN sees:
  1. Sonntagsessen — member
  2. WG — member
```

- **"INVITED, not a member"** — ODIN does not have the profile key of whoever added it. That
  person accepts ODIN's message request and replies to it (step 6 does this for you; another
  admin would have to message ODIN themselves). If ODIN stays invited, remove it from the group
  and add it again.
- Once ODIN is a member of two groups, the wizard asks *Are both groups listed as member?*
  Enter (or `y`) to choose, `n` to keep waiting.
- Then type the **number of the flat group**, then the **number of the dinner group**. They must
  be different groups, and ODIN must be a member of both.

The chosen IDs are stored in ODIN's database; `odib run` reads them from there. (If
`FLAT_GROUP_ID` and `DINNER_GROUP_ID` are both set in `odib.env`, there is nothing to choose and
the step is skipped — see [Group IDs](#group-ids).)

### Step 8 · Test

*Post a test message to the flat group now? [y/N]* — `y` posts the `flat_test` text from the
config to the flat group, so you can see on your phone that ODIN can write there. Enter (or `n`)
skips it. Either way the step counts as answered.

### Step 9 · Done

Shows the number, your number and both group IDs with where they come from (`database` or
`env var`), and reminds you to back up the volume. A running `odib run` notices within 30 s and starts — no
restart needed.

## Checking the setup: `odib setup --status`

```bash
podman exec odib odib setup --status
```

Shows each step with ✓ / ✗ and changes nothing: Signal API reachable, number registered, PIN set,
profile applied, hello answered, both groups chosen — and whether ODIN is still a **member** of
each (✗ *ODIN is not in this group* or *only invited* if someone removed it). Exit code 0 when
fully set up, 1 otherwise, so it also works as a **health check** later, e.g. after restoring a
backup or when ODIN has gone quiet.

## Options

| Command | Use it to |
|---------|-----------|
| `odib setup` | Set up, or continue an interrupted setup. Re-running a finished setup only re-applies the profile. |
| `odib setup --status` | Check what is done (see above). Cannot be combined with the other options. |
| `odib setup --pin` | Enter your own PIN instead of a generated one; also replaces a PIN that is set. |
| `odib setup --redo pin` | Set a new generated PIN. |
| `odib setup --redo hello` | Do the hello again, e.g. with another operator number. |
| `odib setup --redo groups` | Choose the flat and dinner group again, e.g. after a group was replaced. |
| `odib setup --redo test` | Ask about the test message again. |
| `odib setup --reregister` | Register the number again although it is registered (asks you to type `reregister`). See below — usually this cannot work. |

`--redo` can be given several times (`--redo hello --redo groups`). All commands use
`podman exec -it odib …`.

## What the wizard cannot do

- **Force a new registration.** signal-cli-rest-api does not pass signal-cli's `reregister`
  flag, so registering an account that is still in the volume fails with *Signal says the
  account is already registered*. `--reregister` therefore only gets as far as that message.
  Really starting over means removing ODIN's account data from the Signal volume first, which
  throws away its keys — make an extra backup copy before (see below), and do not do this while
  the registration lock might still hold: see the next point.
- **Register with a registration lock PIN.** The wizard never sends ODIN's PIN while verifying.
  If ODIN's account was lost (no backup) and you register again within 7 days of its last
  activity, step 3 ends with the registration-lock message even though you know the PIN. Either
  wait the 7 days, or verify by hand from the `odib` container, after step 2 sent the code
  (`<code>` without dash, `<PIN>` from the password manager):

  ```bash
  podman exec -it odib python -c '
  import os, sys, httpx
  api = os.environ.get("SIGNAL_API_URL", "http://localhost:8080")
  r = httpx.post(f"{api}/v1/register/{os.environ["SIGNAL_NUMBER"]}/verify/{sys.argv[1]}",
                 json={"pin": sys.argv[2]})
  print(r.status_code, r.text)' '<code>' '<PIN>'
  ```

  `201` means registered; run `odib setup` again for the remaining steps.

## Group IDs

- **Normally:** the wizard stores both IDs in ODIN's database (`ODIB_DB`, on the `/data` volume).
  Nothing goes into `odib.env` or the repo. `odib check-config` and `odib setup --status` show
  them and their source.
- **Override:** `FLAT_GROUP_ID` / `DINNER_GROUP_ID` in `odib.env` take precedence over the
  database while they are set (use the `id` form including the `group.` prefix). Only for special
  cases, e.g. testing against another group; the wizard reminds you when one is set.
- **Debugging:** `podman exec odib odib list-groups` prints the groups ODIN is in, with their IDs.

## Backing up the volume — mandatory

The Signal API container's data volume holds ODIN's private keys. Find where it is on disk (the
volume name is in the deployment's Quadlet units; `podman volume ls` lists it):

```bash
podman volume inspect <signal-volume> --format '{{.Mountpoint}}'
```

- **Primary backup:** the VM is part of the Proxmox backup job (set up in the deploy
  runbook, #10). Check that the job includes the VM and that a backup has run *after* the setup.
- **Optional extra copy** (e.g. before risky changes). The tarball contains the account keys —
  store it like a password (encrypted), never in the repo:

  ```bash
  podman volume export <signal-volume> --output odib-signal-cli-$(date +%F).tar
  ```

Restoring an old backup is fine: Signal does not invalidate the keys over time. Messages received
while the backup was offline are lost; that does not matter for ODIN. After a restore, check with
`odib setup --status`.

**Never run two signal-cli instances on the same account data at the same time**, and never
register the number on another machine while the deployment holds the account — a new
registration replaces ODIN's keys and the volume becomes useless.

## Residual risk and the SIM

- The registration lock protects the number only while ODIN is active: it **expires after 7 days
  of account inactivity**. A recycled number is therefore a risk only if ODIN is offline for more
  than 7 days *and* someone registers the number in that window. If that happens, ODIN's account
  is gone and we need the number back to register again.
  Sources: [Signal support: Registration Lock](https://support.signal.org/hc/en-us/articles/360007059792),
  [Privacy Guides: Signal number registration update](https://www.privacyguides.org/articles/2022/11/10/signal-number-registration-update).
- With the PIN set and the volume backed up, the SIM itself is no longer needed for day-to-day
  operation.
- Optional: top up the prepaid SIM about once a year so the provider does not revoke it — check
  the provider's inactivity rules and put a reminder in your calendar.
- Numberless (username-only) accounts were considered and postponed until signal-cli and
  signal-cli-rest-api support them
  ([signal-cli#2124](https://github.com/AsamK/signal-cli/issues/2124),
  [signal-cli-rest-api#889](https://github.com/bbernhard/signal-cli-rest-api/issues/889)).

## Troubleshooting

- **Anything fails in the Signal API:** its logs show signal-cli's own error messages. Find the
  container with `podman ps` (the Signal API container of the `odib` pod), then
  `podman logs <container>`, or `journalctl --user -u signal-api` for its Quadlet unit.
- **The wizard stops with *The Signal API call failed: …*:** the message is signal-cli's. Fix the
  cause (often: API restarting, network) and run `odib setup` again — it continues where it
  stopped.
- **Sending fails with a rate-limit / "proof required" error** (in the bot's logs or in step 6/8):
  Signal wants a captcha for sending. Get a token as in step 1, but from
  <https://signalcaptchas.org/challenge/generate.html>, and submit it together with the
  `challenge_token` from the error message. Here the captcha is passed **with** its
  `signalcaptcha://` prefix. The Signal API is only reachable inside the pod, so run it from the
  `odib` container:

  ```bash
  podman exec -it odib python -c '
  import os, sys, httpx
  api = os.environ.get("SIGNAL_API_URL", "http://localhost:8080")
  r = httpx.post(f"{api}/v1/accounts/{os.environ["SIGNAL_NUMBER"]}/rate-limit-challenge",
                 json={"challenge_token": sys.argv[1], "captcha": sys.argv[2]})
  print(r.status_code, r.text)' '<challenge_token>' 'signalcaptcha://signal-hcaptcha.…'
  ```

- **You cannot find ODIN on your phone by number:** after step 6, ODIN is in your chat list and
  can be added to groups from there.

## References

Verified against signal-cli-rest-api **0.101** (signal-cli 0.14.8).

- Endpoint examples: [doc/EXAMPLES.md](https://github.com/bbernhard/signal-cli-rest-api/blob/master/doc/EXAMPLES.md)
- Full API (Swagger): <https://bbernhard.github.io/signal-cli-rest-api/>
- Handlers and request bodies: [src/api/api.go](https://github.com/bbernhard/signal-cli-rest-api/blob/master/src/api/api.go)
- [signal-cli wiki: Registration with captcha](https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha)
- signal-cli commands behind the API (`register`, `verify`, `setPin`, `updateProfile`):
  [signal-cli man page](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc)
