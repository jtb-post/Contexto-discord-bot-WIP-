"""SQLite persistence: per-server config, rounds, guesses. Points are derived
from rounds won, so the leaderboard can be filtered by period."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id        INTEGER PRIMARY KEY,
    channel_id      INTEGER,
    cooldown_min    INTEGER NOT NULL DEFAULT 10,
    hints_per_round INTEGER NOT NULL DEFAULT 3,
    next_round_at   INTEGER,
    manager_role_id INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id         INTEGER NOT NULL,
    number           INTEGER NOT NULL,
    secret           TEXT    NOT NULL,
    started_at       INTEGER NOT NULL,
    ended_at         INTEGER,
    winner_id        INTEGER,
    guess_count      INTEGER,
    hints_used       INTEGER NOT NULL DEFAULT 0,
    board_channel_id INTEGER,
    board_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS rounds_by_guild ON rounds(guild_id, ended_at);
CREATE TABLE IF NOT EXISTS guesses (
    round_id INTEGER NOT NULL REFERENCES rounds(id),
    word     TEXT    NOT NULL,
    user_id  INTEGER NOT NULL,
    rank     INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    is_hint  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (round_id, word)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._all("PRAGMA table_info(guilds)")}
        if "manager_role_id" not in cols:
            self.conn.execute("ALTER TABLE guilds ADD COLUMN manager_role_id INTEGER")

    def _one(self, sql: str, *args):
        return self.conn.execute(sql, args).fetchone()

    def _all(self, sql: str, *args):
        return self.conn.execute(sql, args).fetchall()

    # --- guild config ---------------------------------------------------------

    def get_guild(self, guild_id: int):
        return self._one("SELECT * FROM guilds WHERE guild_id = ?", guild_id)

    def configure(
        self, guild_id: int, channel_id: int, cooldown_min: int, hints_per_round: int,
        manager_role_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO guilds (guild_id, channel_id, cooldown_min, hints_per_round, manager_role_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id,
                   cooldown_min = excluded.cooldown_min, hints_per_round = excluded.hints_per_round,
                   manager_role_id = excluded.manager_role_id""",
            (guild_id, channel_id, cooldown_min, hints_per_round, manager_role_id),
        )

    # --- bot-wide settings (e.g. the dev server) --------------------------------

    def get_setting(self, key: str) -> str | None:
        row = self._one("SELECT value FROM settings WHERE key = ?", key)
        return row["value"] if row else None

    def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- data deletion (Privacy Policy) -----------------------------------------

    def _transaction(self, *statements: tuple[str, tuple]) -> None:
        self.conn.execute("BEGIN")
        try:
            for sql, args in statements:
                self.conn.execute(sql, args)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def delete_user(self, user_id: int) -> None:
        """Remove a user's guesses and wins in every server."""
        self._transaction(
            ("DELETE FROM guesses WHERE user_id = ?", (user_id,)),
            ("UPDATE rounds SET winner_id = NULL WHERE winner_id = ?", (user_id,)),
        )

    def delete_guild(self, guild_id: int) -> None:
        """Remove everything stored for a server."""
        self._transaction(
            ("DELETE FROM guesses WHERE round_id IN (SELECT id FROM rounds WHERE guild_id = ?)", (guild_id,)),
            ("DELETE FROM rounds WHERE guild_id = ?", (guild_id,)),
            ("DELETE FROM guilds WHERE guild_id = ?", (guild_id,)),
        )

    def set_next_round_at(self, guild_id: int, ts: int | None) -> None:
        self.conn.execute("UPDATE guilds SET next_round_at = ? WHERE guild_id = ?", (ts, guild_id))

    def pending_rounds(self):
        return self._all(
            "SELECT guild_id, next_round_at FROM guilds WHERE next_round_at IS NOT NULL AND channel_id IS NOT NULL"
        )

    # --- rounds ---------------------------------------------------------------

    def active_rounds(self):
        return self._all("SELECT * FROM rounds WHERE ended_at IS NULL")

    def next_round_number(self, guild_id: int) -> int:
        row = self._one("SELECT COALESCE(MAX(number), 0) + 1 AS n FROM rounds WHERE guild_id = ?", guild_id)
        return row["n"]

    def recent_secrets(self, guild_id: int, limit: int = 100) -> set[str]:
        rows = self._all(
            "SELECT secret FROM rounds WHERE guild_id = ? ORDER BY id DESC LIMIT ?", guild_id, limit
        )
        return {r["secret"] for r in rows}

    def create_round(self, guild_id: int, number: int, secret: str, now: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO rounds (guild_id, number, secret, started_at) VALUES (?, ?, ?, ?)",
            (guild_id, number, secret, now),
        )
        return cur.lastrowid

    def get_round(self, round_id: int):
        return self._one("SELECT * FROM rounds WHERE id = ?", round_id)

    def set_board(self, round_id: int, channel_id: int, message_id: int) -> None:
        self.conn.execute(
            "UPDATE rounds SET board_channel_id = ?, board_message_id = ? WHERE id = ?",
            (channel_id, message_id, round_id),
        )

    def end_round(self, round_id: int, winner_id: int | None, now: int, guess_count: int) -> None:
        self.conn.execute(
            "UPDATE rounds SET ended_at = ?, winner_id = ?, guess_count = ? WHERE id = ?",
            (now, winner_id, guess_count, round_id),
        )

    def use_hint(self, round_id: int) -> None:
        self.conn.execute("UPDATE rounds SET hints_used = hints_used + 1 WHERE id = ?", (round_id,))

    # --- guesses --------------------------------------------------------------

    def find_guess(self, round_id: int, word: str):
        return self._one("SELECT * FROM guesses WHERE round_id = ? AND word = ?", round_id, word)

    def add_guess(self, round_id: int, word: str, user_id: int, rank: int, now: int, is_hint: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO guesses (round_id, word, user_id, rank, ts, is_hint) VALUES (?, ?, ?, ?, ?, ?)",
            (round_id, word, user_id, rank, now, int(is_hint)),
        )

    def best_rank(self, round_id: int) -> int | None:
        return self._one("SELECT MIN(rank) AS r FROM guesses WHERE round_id = ?", round_id)["r"]

    def round_stats(self, round_id: int) -> tuple[int, int]:
        """(player guesses, distinct players) — hints excluded."""
        row = self._one(
            "SELECT COUNT(*) AS g, COUNT(DISTINCT user_id) AS p FROM guesses WHERE round_id = ? AND is_hint = 0",
            round_id,
        )
        return row["g"], row["p"]

    def top_guesses(self, round_id: int, limit: int = 6):
        return self._all(
            "SELECT word, user_id, rank, is_hint FROM guesses WHERE round_id = ? ORDER BY rank LIMIT ?",
            round_id, limit,
        )

    def all_guesses(self, round_id: int):
        return self._all(
            "SELECT word, user_id, rank, is_hint FROM guesses WHERE round_id = ? ORDER BY rank", round_id
        )

    def runners_up(self, round_id: int, exclude_user: int, limit: int = 2):
        # SQLite returns the bare `word` column from the row that holds MIN(rank).
        return self._all(
            """SELECT user_id, word, MIN(rank) AS rank FROM guesses
               WHERE round_id = ? AND is_hint = 0 AND user_id != ? AND rank > 1
               GROUP BY user_id ORDER BY rank LIMIT ?""",
            round_id, exclude_user, limit,
        )

    # --- leaderboard & stats --------------------------------------------------

    def standings(self, guild_id: int, since: int = 0):
        """Every winner in the period: points (rounds won), fastest solve."""
        return self._all(
            """SELECT winner_id AS user_id, COUNT(*) AS points, MIN(guess_count) AS fastest
               FROM rounds WHERE guild_id = ? AND winner_id IS NOT NULL AND ended_at >= ?
               GROUP BY winner_id ORDER BY points DESC, fastest ASC, MIN(ended_at) ASC""",
            guild_id, since,
        )

    def rounds_played(self, guild_id: int, since: int = 0) -> int:
        return self._one(
            "SELECT COUNT(*) AS n FROM rounds WHERE guild_id = ? AND ended_at IS NOT NULL AND ended_at >= ?",
            guild_id, since,
        )["n"]

    def user_activity(self, guild_id: int, user_id: int):
        return self._one(
            """SELECT COUNT(DISTINCT g.round_id) AS rounds, COUNT(*) AS guesses, MIN(g.rank) AS best
               FROM guesses g JOIN rounds r ON r.id = g.round_id
               WHERE r.guild_id = ? AND g.user_id = ? AND g.is_hint = 0""",
            guild_id, user_id,
        )
