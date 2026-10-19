# Re-register the number

**How-to guide** — steps for one task you already know you want to do.

Set up ODIN's Signal account again, or with another number.

You need this only when ODIN's account is gone — the `odin-signal` volume is lost and there is
no backup — or when you deliberately start over. If a backup exists,
[restore it](backup-restore.md) instead: it needs no SIM and keeps ODIN in its groups.

Commands on the VM run as the `odin` user (`sudo machinectl shell odin@`).

## Before you start

- The **SIM** for ODIN's number, in a phone, for the verification code.
- The PIN from the password manager entry *"ODIN Signal registration lock PIN"*, if you register
  again within 7 days of ODIN's last activity.
- Your own phone with Signal, in both groups.

## Register again after the account was lost

1. If the Signal volume still exists but is broken, keep a copy of it first
   ([extra copy](backup-restore.md#make-an-extra-copy-of-a-volume)).
2. Start with an empty Signal volume. The wizard cannot force a new registration over an account
   that is still in the volume (it stops with *Signal says the account is already registered*),
   so remove it:

    ```bash
    systemctl --user stop odin-pod
    podman volume rm odin-signal
    systemctl --user start odin-pod      # creates an empty odin-signal
    ```

    This throws away ODIN's keys for good.

3. Run the wizard:

    ```bash
    podman exec -it odin odin setup
    ```

    It goes through captcha, code, PIN, profile and hello as in
    [First deployment](../../tutorials/first-deployment.md). At the code step Signal may say the
    number is locked with a PIN:
    - **ODIN's own lock** (within 7 days of its last activity): enter the PIN from the password
      manager. The account keeps it; no new PIN is set.
    - **A previous owner's lock**: press Enter. The wizard stops; the lock expires 7 days after
      that account was last active. Run `odin setup` again after that.

4. The new account is not in the groups any more. On your phone, add Odin 🍽️ to the flat group
   and the dinner group again. The stored group IDs stay valid; to choose other groups, see
   [Change the groups](change-groups.md).
5. Check:

    ```bash
    podman exec odin odin setup --status
    ```

6. Run the Proxmox backup job once by hand
   ([check the backup](backup-restore.md#check-the-backup-after-setup)).

## Use another number

1. Set the new number in `~/odin/odin.env`: `SIGNAL_NUMBER=+49…` (E.164, no spaces).
2. Restart the bot: `systemctl --user restart odin`.
3. Continue with step 3 above (`odin setup`): registration, PIN, profile and hello are done again
   for the new number. Then add the new account to both groups.

## Change only the PIN

```bash
podman exec -it odin odin setup --redo pin     # a new generated PIN
podman exec -it odin odin setup --pin          # a PIN you choose
```

Store the new PIN in the password manager entry. All options: [CLI](../../reference/cli.md).

## Keep the number safe

- The registration lock protects the number only while ODIN is active: it expires after
  **7 days of inactivity**. Do not leave ODIN offline for longer than that, or someone who gets
  the recycled number can register it.
- With the PIN set and the volume backed up, the SIM is not needed day to day. Keep it alive:
  top up the prepaid SIM about once a year (check the provider's inactivity rules) and put a
  reminder in your calendar.

## See also

- [Signal support: Registration Lock](https://support.signal.org/hc/en-us/articles/360007059792)
- [Privacy Guides: Signal number registration update](https://www.privacyguides.org/articles/2022/11/10/signal-number-registration-update)
- [signal-cli wiki: Registration with captcha](https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha)
