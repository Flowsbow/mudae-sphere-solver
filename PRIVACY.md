# Privacy policy

This covers the Discord bot run from this repository (Sphere Solver). If you run your
own copy, you're responsible for your copy's data.

Last updated: 2026-10-08. Changes are made in this file, so its commit history shows
every earlier version.

## What the bot reads

- **Slash commands and right-click commands you use**, with the options you type
  (for example a board you enter in `/manual-input`).
- **Messages in channels it can see**, through Discord's Message Content intent. It
  acts on only two kinds: `$oc`, `$oq` and `$oh` commands typed by people who
  turned on `/autoread`, and the Mudae bot's game boards and rewards messages.
  Everything else is ignored.
- **A message you right-click** with **Solve sphere board** or **Inspect sphere
  board**. Inspect sends you a private file describing that message's buttons; the
  bot keeps no copy.

Messages are held in memory only: discord.py keeps the most recent 1,000 so the bot
can follow edits to a Mudae board. Message text is never written to disk or logged.

## What the bot saves

Three files on the bot's server:

| File | Contents | Discord IDs |
| --- | --- | --- |
| `settings.json` | Who has `/autoread` and `/colorblindmode` on, and `/spherebonus` values | Your user ID; with a sphere bonus, also the server ID it's set for |
| `my_stats.json` | Your totals from auto-read games: games, spheres gained, spheres clicked per color, how often you followed the solver, how your scores compared with its predictions, and which `$oc` cells held the red | Your user ID |
| `stats.json` | The same totals added up over all players | None |

Stats are running totals (counts, sums and sums of squares), never a record of
individual games, and only games read by `/autoread` count.

## What the bot doesn't do

- It doesn't sell or share data with anyone.
- It doesn't use data for advertising or to train machine-learning or AI models.
- It doesn't store message text, usernames, server names or channel IDs.

## Deleting your data

- `/delete-stats` deletes your `my_stats.json` entry after you confirm. Your games
  stay in the global totals, which have no IDs.
- Turning off `/autoread` or `/colorblindmode` removes you from that list in
  `settings.json`.
- Setting `/spherebonus flat: 0 percent: 0` removes your bonus for that server.
- For anything else, message **@flowsbow** on Discord or open an issue on this
  repository.

## Where data is kept

The bot runs on a hosting provider's server in North America. Its owner may keep
private backups of the three files above. The data stays until you delete it or the
bot is shut down.

## Contact

**@flowsbow** on Discord, or an issue at
https://github.com/Flowsbow/mudae-sphere-solver/issues.
