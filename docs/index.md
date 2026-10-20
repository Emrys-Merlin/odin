# ODIN — Open Dinner Invitation Notifier

![ODIN logo: an indigo raven perched in a dinner plate, fork and knife crossed behind it.](assets/logo.png){ width="160" align="right" }

ODIN is a Signal bot that organises a weekly open dinner. Every week it asks the flatmates
whether dinner takes place, tells the guests (or cancels), and counts who is coming so there is
enough food.

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Findet am Sonntag das offene Abendessen statt? 🍽️
Wer da ist und das Abendessen ausrichtet, reagiert bitte bis Mittwoch 18:00 mit 👍 auf diese
Nachricht. Ein 👍 reicht – ohne 👍 sage ich das Abendessen am Mittwoch um 18:00 ab.
<span class="reactions">👍 2</span>
</div>
</div>

Everything ODIN does happens in two Signal groups: the **flat group** decides, the **dinner
group** gets invited. Flatmates can see and change its settings with chat commands such as
`/status` or `/cancel`.

## Where to start

<div class="grid cards" markdown>

- **Learn** — [Tutorials](tutorials/index.md)

    Set up your own ODIN from scratch, or follow a dinner week as a flatmate.

- **Do** — [How-to guides](how-to/index.md)

    Upgrade, back up, cancel a dinner, edit a text, add a command.

- **Look up** — [Reference](reference/index.md)

    CLI, chat commands, templates, configuration, deployment units.

- **Understand** — [Explanation](explanation/index.md)

    The weekly cycle, reaction rules, reliability, architecture, design goals.

</div>

**I live in the flat** — start with [Your first week with ODIN](tutorials/first-week.md), then
the [chat how-tos](how-to/chat/cancel-dinner.md).

**I run ODIN** — start with [First deployment](tutorials/first-deployment.md), then the
[operating how-tos](how-to/operate/upgrade.md).

**I want to contribute** — see [Run locally](how-to/develop/run-locally.md) and `CLAUDE.md` in
the [repository](https://github.com/Emrys-Merlin/odin).
