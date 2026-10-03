# Runbook: register ODIN's Signal number and join the groups

One-time setup, done by Tim. At the end you have:

- a podman volume **`odib-signal-cli`** holding ODIN's Signal account (keys!),
- the account registered as a **primary** device with profile name **Odin 🍽️** and a
  registration lock PIN,
- ODIN in the flat group and the dinner group,
- the values for `SIGNAL_NUMBER`, `FLAT_GROUP_ID` and `DINNER_GROUP_ID`.

Allow 30 minutes. You need: the SIM card for ODIN's number in a phone (to receive the code), your
own phone with Signal, a desktop browser, and your password manager.

## Background

- ODIN talks to Signal through
  [`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api), a REST
  wrapper around [signal-cli](https://github.com/AsamK/signal-cli). Registration uses the same
  container and the same data volume as the deployment (#10), just started by hand.
- Everything that makes ODIN *be* ODIN — identity keys, account password, group memberships —
  lives in the container's signal-cli data directory, `/home/.local/share/signal-cli`, which we
  put on the named volume `odib-signal-cli`. **Losing this volume means re-registering, which
  needs the SIM.**
- We register a regular SIM number. The SIM provider may recycle the number one day if it is
  unused, so the account must not depend on it: a **registration lock PIN** stops anyone else from
  registering the number while ODIN is active, and the **volume backup** means we never need to
  register again. See [Residual risk](#residual-risk-and-the-sim).

Verified against signal-cli-rest-api **0.101** (signal-cli 0.14.8), the `latest` image as of
2026-10. API references:

- Endpoint examples: [doc/EXAMPLES.md](https://github.com/bbernhard/signal-cli-rest-api/blob/master/doc/EXAMPLES.md)
- Full API (Swagger): <https://bbernhard.github.io/signal-cli-rest-api/>
- Handlers and request bodies: [src/api/api.go](https://github.com/bbernhard/signal-cli-rest-api/blob/master/src/api/api.go)
- signal-cli commands behind them (`register`, `verify`, `setPin`, `updateProfile`):
  [signal-cli man page](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc)

## 0. Where to run this

Run it **on the deployment VM as the `odib` user**, so the volume ends up where the deployment
(#10, [deploy.md](deploy.md)) expects it. You need from the deploy runbook: the Debian VM, podman,
and the `odib` user with lingering enabled. Log in as `odib` with a real login session (rootless
podman needs one; plain `sudo -u odib` is not enough):

```bash
ssh odib@<vm>
# or, from another account on the VM (needs the systemd-container package):
sudo machinectl shell odib@
```

Install the two helper tools used below (as an admin user, once):

```bash
sudo apt install -y curl jq
```

> Registering on another machine (e.g. your laptop) also works: follow this runbook there, then
> move the volume with [Moving the volume to the VM](#moving-the-volume-to-the-vm).

**Never run two signal-cli instances on the same account data at the same time.** Stop the
deployment pod (if it already exists) before step 1:
`systemctl --user stop odib-pod.service`.

## 1. Start the Signal API container

As `odib`:

```bash
podman volume create odib-signal-cli

podman run -d --name signal-api-setup \
  -p 127.0.0.1:8080:8080 \
  -e MODE=json-rpc \
  -v odib-signal-cli:/home/.local/share/signal-cli \
  docker.io/bbernhard/signal-cli-rest-api:latest
```

- `-p 127.0.0.1:8080:8080` makes the API reachable from this machine only.
- `MODE=json-rpc` is the mode the deployment uses (a long-running signal-cli daemon).
- The image runs as its own unprivileged user; on first use podman copies the image's (empty)
  data directory with its ownership into the new volume, so no `chown` is needed.

Set up the shell variables and a small helper. **Keep this shell open for the whole runbook**;
if you open a new one, run this block again.

```bash
export SIGNAL_NUMBER='+49…'   # ODIN's number, E.164: +, country code, no leading 0, no spaces
export API=http://127.0.0.1:8080

# POST/PUT/GET JSON and always show the HTTP status
api() { curl -sS -w '\nHTTP %{http_code}\n' -H 'Content-Type: application/json' "$@"; }
```

Wait until the API is up (the daemon takes 10–30 s to start), then check it:

```bash
until curl -sf "$API/v1/health"; do sleep 2; done; echo ready
api "$API/v1/about"
```

`/v1/about` prints JSON with `"mode":"json-rpc"` and the version. If it never becomes ready:
`podman logs signal-api-setup`.

## 2. Get a captcha token

Signal requires a captcha for registration. The token is valid only for **a minute or two**, so
have step 3 ready to paste before you start.

1. Open <https://signalcaptchas.org/registration/generate.html> in a desktop browser and solve
   the captcha.
2. The page then shows an **"Open Signal"** link. Right-click it → *Copy link*. (Alternatively:
   open the browser's developer console; a line says that navigation to
   `signalcaptcha://signal-hcaptcha…` was prevented.)
3. The token is everything **after** `signalcaptcha://` — it starts with
   `signal-hcaptcha` (or similar) and is long. Set it:

```bash
export CAPTCHA='signal-hcaptcha.…'   # without the signalcaptcha:// prefix
```

Source: [EXAMPLES.md → "Register a number (with captcha)"](https://github.com/bbernhard/signal-cli-rest-api/blob/master/doc/EXAMPLES.md),
[signal-cli wiki: Registration with captcha](https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha).

## 3. Register (SMS or voice)

`POST /v1/register/{number}` with body `{"captcha": …, "use_voice": …}`.

**Via SMS** (the normal case for a SIM):

```bash
jq -n --arg c "$CAPTCHA" '{captcha: $c}' | api -X POST -d @- "$API/v1/register/$SIGNAL_NUMBER"
```

**Via voice call** (if no SMS arrives, or the number cannot receive SMS):

```bash
jq -n --arg c "$CAPTCHA" '{captcha: $c, use_voice: true}' | api -X POST -d @- "$API/v1/register/$SIGNAL_NUMBER"
```

Expected: `HTTP 201` and an empty body. Signal then sends a 6-digit code by SMS, or calls and
reads it out.

| Response | Meaning / fix |
|----------|---------------|
| `Captcha required for verification` / `Invalid captcha` | Token expired or was copied wrongly. Go back to step 2 and be quick. |
| `Couldn't use SMS verification … try again with {"use_voice": true}` | Signal wants a voice call. Wait **60 s**, get a fresh captcha, run the voice variant. |
| Voice call is refused right after an SMS attempt | Signal only allows voice after an SMS attempt and a wait; wait 60 s and retry with a fresh captcha. |
| `429` / `Rate limit exceeded` | Too many attempts. Wait (minutes to hours) and retry. |

## 4. Verify the code

`POST /v1/register/{number}/verify/{code}`. Type the code **without** the dash:

```bash
export CODE=123456
api -X POST "$API/v1/register/$SIGNAL_NUMBER/verify/$CODE"
```

Expected: `HTTP 201`. Check that the account exists:

```bash
api "$API/v1/accounts"
```

prints `["+49…"]` with ODIN's number.

If verify fails with a message about a **registration lock / PIN**, the number still has a lock
set by a previous owner of the SIM. It expires 7 days after that account was last active; there
is nothing else to do but wait and register again from step 2.

## 5. Set the registration lock PIN

`POST /v1/accounts/{number}/pin` with body `{"pin": …}` (signal-cli `setPin`: "Set a
registration lock pin, to prevent others from registering your account's phone number").

1. Create a new entry **"ODIN Signal registration lock PIN"** in your password manager. Generate a
   PIN there (at least 6 digits; longer and alphanumeric is fine), and save the entry together
   with ODIN's number. This is the only copy — Signal cannot recover it.
2. Set it. `read -rs` keeps the PIN out of the shell history and off the screen; paste it and
   press Enter:

```bash
read -rs PIN
jq -n --arg p "$PIN" '{pin: $p}' | api -X POST -d @- "$API/v1/accounts/$SIGNAL_NUMBER/pin"
unset PIN
```

Expected: `HTTP 201`.

From now on, registering ODIN's number anywhere else requires this PIN, as long as ODIN has been
active within the last 7 days. ODIN itself never needs the PIN again unless we have to register
from scratch (then: step 4 with body `{"pin": "<PIN>"}`, see `VerifyNumberSettings` in
[api.go](https://github.com/bbernhard/signal-cli-rest-api/blob/master/src/api/api.go)).

## 6. Set the profile name

`PUT /v1/profiles/{number}` with body `{"name": …, "base64_avatar": …}`.

```bash
jq -n '{name: "Odin 🍽️"}' | api -X PUT -d @- "$API/v1/profiles/$SIGNAL_NUMBER"
```

Expected: `HTTP 204`.

Optional avatar (a square PNG or JPEG, a few hundred KB at most), sent together with the name:

```bash
jq -n --rawfile a <(base64 -w0 odin.png) '{name: "Odin 🍽️", base64_avatar: $a}' \
  | api -X PUT -d @- "$API/v1/profiles/$SIGNAL_NUMBER"
```

## 7. Say hello to Tim

Signal only lets you add someone to a group as a full member if you already know their *profile
key*, which they share by messaging you. Without this step ODIN would show up in the groups as
"invited" instead of as a member. So ODIN sends you a direct message first:

```bash
export TIM_NUMBER='+49…'   # your own Signal number

jq -n --arg n "$SIGNAL_NUMBER" --arg r "$TIM_NUMBER" \
  '{number: $n, recipients: [$r], message: "Hallo, ich bin Odin 🍽️ – hello, I am Odin."}' \
  | api -X POST -d @- "$API/v2/send"
```

Expected: `HTTP 201` and `{"timestamp":"…"}`.

On your phone:

1. Open the message request from **Odin 🍽️** and tap **Accept**.
2. Save ODIN as a contact (ODIN's number, name "Odin 🍽️") — optional, but makes adding it easier.
3. Reply anything (e.g. "👋") so ODIN also learns your profile key.

## 8. Add ODIN to both groups

On your phone, in the **flat group** and then in the **dinner group**: group settings → *Add
members* → Odin 🍽️ → add.

ODIN must be a full member, not just "invited": in the member list, ODIN appears under the
members, not under *Pending / invited*. If it is only invited, remove the invitation, make sure
step 7 is done (you accepted ODIN's message), and add ODIN again.

Group admins: ODIN does not need to be an admin. If a group only lets admins add members, an
admin has to do this step.

## 9. List the group IDs

`GET /v1/groups/{number}` lists the groups ODIN is in. (Once #7 is merged, `odib list-groups`
prints the same.)

```bash
curl -sS "$API/v1/groups/$SIGNAL_NUMBER" | jq '.[] | {name, member, id}'
```

Example output:

```json
{
  "name": "WG",
  "member": true,
  "id": "group.a0RVUHdhT295V3JUOHZNSjVtQi9zOEdjRndWdjhHeGUyakYzZTltSXVPMD0="
}
```

- Both groups must be listed with `"member": true`. If a group is missing, wait a few seconds
  and run the command again (ODIN learns about the group from an incoming update); if it stays
  missing or `"member": false`, redo step 8 for it.
- Use the **`id`** field, *including* the `group.` prefix. It is the form the REST API sends to.
  (The `internal_id` field is the raw ID that appears in incoming messages; ODIN derives it
  itself.)

Optional end-to-end check — ODIN posts in the flat group (skip it if you do not want the noise):

```bash
export FLAT_GROUP_ID='group.…'
jq -n --arg n "$SIGNAL_NUMBER" --arg g "$FLAT_GROUP_ID" \
  '{number: $n, recipients: [$g], message: "Hallo, ich bin Odin 🍽️ und organisiere ab jetzt das Sonntagsessen."}' \
  | api -X POST -d @- "$API/v2/send"
```

## 10. Record the values

| Value | Example | Goes to |
|-------|---------|---------|
| ODIN's number | `+4915…` | `SIGNAL_NUMBER` in the deployment env file (`odib.env`, see [deploy.md](deploy.md)), and the password manager entry |
| `id` of the flat group | `group.a0RV…` | `FLAT_GROUP_ID` in `odib.env` |
| `id` of the dinner group | `group.WlVm…` | `DINNER_GROUP_ID` in `odib.env` |
| Registration lock PIN | — | Password manager only (step 5). Never in the repo or in `odib.env`. |
| Volume `odib-signal-cli` | — | Stays on the VM, mounted by the deployment's Signal API container. Backed up with the VM. |

None of these go into the repo. The group IDs are not secret, but they and the number are
deployment-specific.

## 11. Stop the setup container

```bash
podman rm -f signal-api-setup
```

This removes the container only; the account stays on the volume `odib-signal-cli`:

```bash
podman volume ls        # odib-signal-cli is still listed
```

From here on, only the deployment (#10) uses the volume. Do **not** register the number again
while the deployment holds the account — a new registration replaces ODIN's keys and the volume
becomes useless.

## Backing up the volume — mandatory

The volume holds ODIN's private keys. Find where it is on disk:

```bash
podman volume inspect odib-signal-cli --format '{{.Mountpoint}}'
# /home/odib/.local/share/containers/storage/volumes/odib-signal-cli/_data
```

- **Primary backup:** the VM is part of the Proxmox backup job (set up in [deploy.md](deploy.md),
  #10). Check that the job includes the VM and that a backup has run *after* this registration.
- **Optional extra copy** (e.g. before risky changes). The tarball contains the account keys —
  store it like a password (encrypted), never in the repo:

  ```bash
  podman volume export odib-signal-cli --output odib-signal-cli-$(date +%F).tar
  ```

Restoring an old backup is fine: Signal does not invalidate the keys over time. Messages received
while the backup was offline are lost; that does not matter for ODIN.

## Moving the volume to the VM

Only needed if you registered on another machine. On that machine:

```bash
podman rm -f signal-api-setup
podman volume export odib-signal-cli --output odib-signal-cli.tar
scp odib-signal-cli.tar odib@<vm>:
```

On the VM as `odib`:

```bash
podman volume create odib-signal-cli
podman volume import odib-signal-cli odib-signal-cli.tar
rm odib-signal-cli.tar
```

Then delete the volume and the tarball on the other machine (`podman volume rm odib-signal-cli`),
so the account is never used from two places.

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

- **Anything fails:** `podman logs signal-api-setup` shows signal-cli's own error messages.
- **`HTTP 400` with `User … is not registered`** on steps 5–9: step 4 did not succeed; check
  `api "$API/v1/accounts"`.
- **Sending fails with a rate-limit / "proof required" error:** Signal wants a captcha for
  sending. Get a token as in step 2, but from
  <https://signalcaptchas.org/challenge/generate.html>, then submit it with the `challenge_token`
  from the error message. Here the captcha is passed **with** its `signalcaptcha://` prefix:

  ```bash
  jq -n --arg t '<challenge_token>' --arg c 'signalcaptcha://signal-hcaptcha.…' \
    '{challenge_token: $t, captcha: $c}' \
    | api -X POST -d @- "$API/v1/accounts/$SIGNAL_NUMBER/rate-limit-challenge"
  ```
- **You cannot find ODIN on your phone by number:** use step 7 — once ODIN has messaged you, it
  appears in your chat list and can be added from there.
