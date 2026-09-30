# Contexto for Discord

A Discord bot version of Contexto. Players type single words in one channel. The bot ranks each
guess from 1 to 50,000 by how close its meaning is to a secret word. The first person to guess the
exact word gets a point, and `/leaderboard` shows the server's top 5.

## Two kinds of people

- **The host** runs the bot on their computer or a server. Only the host ever has the bot token.
- **Server managers** add the bot with an invite link and run `/contexto setup`. They never see or
  need the token.

## Host setup (one time)

1. **Create the app.** Go to <https://discord.com/developers/applications> and choose
   New Application.
   - **Bot** tab: turn on **Message Content Intent**. The bot needs it to read guesses.
   - **General Information** tab: fill in **Terms of Service URL** and **Privacy Policy URL**
     (see below).
   - **Installation** tab: tick **Guild Install**, set Install Link to **Discord Provided Link**,
     choose scopes `bot` and `applications.commands`, and permissions View Channels, Send
     Messages, Embed Links, Read Message History, Add Reactions and Manage Messages. Anyone can
     then add the bot from its profile ("Add App") or with the link.

     ---Put the URL into any browser to add the bot to the discord.

2. **Double-click `Start Contexto.bat`.** That's all there is to it.
   - The first time, it creates the Python environment, installs the packages, downloads the
     word list (about 128 MB), then asks for your bot token (in the discord application bot area, click the reset token button, and it will give you it). Paste the token and press Enter;
     it stays hidden while you type. It's saved to `.env` on this computer only, and `.env` is
     git-ignored, so the token never goes into the code.
   - After that, a double-click just starts the bot. Keep the window open while the bot runs;
     closing it stops the bot.
   - If the bot crashes, the launcher restarts it after 10 seconds. If there's a setup problem,
     like a bad token or Message Content Intent being off, it shows what to fix and waits
     instead of restarting.
   - Double-click **`Create Desktop Shortcut.bat`** once to put a "Contexto Bot" icon on your
     desktop.
   - You need Python 3.10 or newer. If it's missing, the launcher opens the download page.

   On a Mac, Linux or a hosting service, run `pip install -r requirements.txt`,
   `python prepare_vectors.py` and `python bot.py`, with the `DISCORD_TOKEN` environment
   variable set.

### Terms of Service and Privacy Policy

Discord requires both links for verified apps, and the bot shows them as buttons.
They are in `docs/terms.md` and `docs/privacy.md`.

1. Replace `[OPERATOR NAME]` and `[CONTACT EMAIL]` in both files.
2. Publish the files. For example, push this project to GitHub and turn on
   **Settings → Pages → Deploy from branch → `/docs`**. They'll be served at
   `https://<you>.github.io/<repo>/terms` and `.../privacy`.
3. Put those URLs in the Developer Portal's General Information tab. Also add them to `.env` as
   `TERMS_URL` and `PRIVACY_URL` so the bot's buttons appear.

### Dev server (owner only)

To make slash commands appear instantly in one test server while you develop, mention the bot in
that server:

| Command | What |
|---|---|
| `@Contexto devguild` | Show the current dev server |
| `@Contexto devguild set [server_id]` | Make this server (or that ID) the dev server; commands sync there only |
| `@Contexto devguild clear` | Go back to global commands for every server |
| `@Contexto sync` | Re-sync commands after changing them |

Only the owner of the app in the Developer Portal can run these (every member, if the app belongs
to a Team). The setting is saved in the database, so it isn't in the code or `.env`.

## Server setup

A server manager adds the bot, then runs
`/contexto setup channel:#contexto [cooldown_minutes] [hints_per_round] [manager_role]`.

- `manager_role` is optional. It picks a role that can end rounds with `/contexto giveup`.
  People with Manage Server can always do this.
- Server Settings → Integrations → Contexto can also restrict any command to chosen roles or
  channels.

## How it plays

- A guess in the game channel is any message that is exactly one word. The bot replies with the
  guess's rank and a bar: 🟩 close (1–300), 🟨 warm (up to 1,500), 🟥 cold.
- If a message has more than one word, the bot sends a short reply saying it was ignored and
  deletes that reply after a few seconds.
- If the bot doesn't know the word, it reacts with ❓.
- If a word was already guessed, the bot says who guessed it first and what rank it got.
- A **live board** of the six closest guesses is pinned in the channel and updated as people guess.
- When someone guesses the exact word, the bot posts a win card with the round's stats and
  **+1 point** for the winner.
- The next round starts on its own after a cooldown.

| Command | Who | What |
|---|---|---|
| `/contexto setup` | Manage Server | Choose the game channel, settings and manager role |
| `/contexto start` | anyone | Start a round if none is running |
| `/contexto board` | anyone | Post the live board again |
| `/contexto hint` | anyone | Reveal a closer word (limited per round) |
| `/contexto giveup` | game managers | End the round and reveal the word |
| `/contexto help` | anyone | Rules, invite, Terms and Privacy buttons |
| `/contexto invite` | anyone | Link to add the bot to another server |
| `/contexto privacy` | anyone | What's stored, and links to the Terms and Privacy Policy |
| `/contexto forget-me` | anyone | Delete your guesses and points from every server |
| `/leaderboard [period]` | anyone | Top 5 by points: all-time, this month or this week |
| `/stats [user]` | anyone | Points, rank, rounds played, fastest solve |

## Notes

- Ranking uses cosine similarity between GloVe vectors, over the 50,000 most common words.
- Secret words come from `secret_words.txt`.
- All data is kept in SQLite (`contexto.db`). When the bot is removed from a server, that
  server's data is deleted, as the Privacy Policy says.
- Tests: `python -m unittest discover -s tests -t .`
