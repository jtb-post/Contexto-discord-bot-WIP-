import tempfile
import unittest
from pathlib import Path

import numpy as np

from contexto import render
from contexto.engine import WordSpace, band, pick_secret
from contexto.store import Store


def tiny_space():
    vocab = ["ocean", "sea", "wave", "beach", "pizza", "keyboard"]
    vectors = np.array([
        [1.0, 0.0, 0.0],
        [0.95, 0.1, 0.0],
        [0.8, 0.3, 0.1],
        [0.6, 0.5, 0.2],
        [0.0, 1.0, 0.3],
        [0.0, 0.2, 1.0],
    ])
    return WordSpace(vocab, vectors)


class EngineTests(unittest.TestCase):
    def test_secret_is_rank_one_and_order_follows_similarity(self):
        r = tiny_space().ranking("ocean")
        self.assertEqual([r.rank(w) for w in ["ocean", "sea", "wave", "beach"]], [1, 2, 3, 4])
        self.assertEqual(r.word_at(2), "sea")
        self.assertIsNone(r.rank("nope"))

    def test_duplicate_vectors_still_put_secret_first(self):
        space = WordSpace(["a", "b"], np.array([[1.0, 0.0], [1.0, 0.0]]))
        self.assertEqual(space.ranking("b").rank("b"), 1)

    def test_bands(self):
        self.assertEqual([band(1), band(300), band(301), band(1500), band(1501)],
                         ["close", "close", "warm", "warm", "cold"])

    def test_pick_secret_avoids_recent(self):
        self.assertEqual(pick_secret(["a", "b"], {"a"}), "b")
        self.assertIn(pick_secret(["a"], {"a"}), ["a"])  # falls back when all used

    def test_tiles_do_not_form_flags(self):
        self.assertEqual(render.tiles("ca").count(" "), 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_round_flow_and_leaderboard(self):
        s = self.store
        s.configure(1, 100, 10, 3)
        rid = s.create_round(1, s.next_round_number(1), "ocean", 1000)
        s.add_guess(rid, "pizza", 11, 5, 1001)
        s.add_guess(rid, "sea", 12, 2, 1002)
        s.add_guess(rid, "wave", 12, 3, 1003)
        s.add_guess(rid, "beach", 99, 4, 1004, is_hint=True)
        s.add_guess(rid, "ocean", 11, 1, 1005)
        self.assertEqual(s.round_stats(rid), (4, 2))
        self.assertEqual(s.best_rank(rid), 1)
        runners = s.runners_up(rid, exclude_user=11)
        self.assertEqual([(r["user_id"], r["word"], r["rank"]) for r in runners], [(12, "sea", 2)])
        s.end_round(rid, 11, 1010, 4)

        rid2 = s.create_round(1, s.next_round_number(1), "sea", 2000)
        s.add_guess(rid2, "sea", 12, 1, 2001)
        s.end_round(rid2, 12, 2002, 1)
        rid3 = s.create_round(1, s.next_round_number(1), "wave", 3000)
        s.end_round(rid3, 11, 3001, 9)

        rows = s.standings(1)
        self.assertEqual([(r["user_id"], r["points"], r["fastest"]) for r in rows], [(11, 2, 4), (12, 1, 1)])
        self.assertEqual([r["user_id"] for r in s.standings(1, since=2500)], [11])
        self.assertEqual(s.rounds_played(1), 3)
        self.assertEqual(s.recent_secrets(1), {"ocean", "sea", "wave"})
        self.assertEqual(s.user_activity(1, 12)["guesses"], 3)
        self.assertEqual(s.active_rounds(), [])

    def test_settings_and_manager_role(self):
        s = self.store
        self.assertIsNone(s.get_setting("dev_guild_id"))
        s.set_setting("dev_guild_id", "42")
        self.assertEqual(s.get_setting("dev_guild_id"), "42")
        s.set_setting("dev_guild_id", None)
        self.assertIsNone(s.get_setting("dev_guild_id"))
        s.configure(1, 100, 10, 3, 777)
        self.assertEqual(s.get_guild(1)["manager_role_id"], 777)
        s.configure(1, 100, 10, 3)
        self.assertIsNone(s.get_guild(1)["manager_role_id"])

    def test_delete_user_and_guild(self):
        s = self.store
        s.configure(1, 100, 10, 3)
        s.configure(2, 200, 10, 3)
        r1 = s.create_round(1, 1, "ocean", 0)
        s.add_guess(r1, "sea", 11, 2, 1)
        s.add_guess(r1, "ocean", 11, 1, 2)
        s.add_guess(r1, "wave", 12, 3, 3)
        s.end_round(r1, 11, 4, 3)
        r2 = s.create_round(2, 1, "sea", 0)
        s.add_guess(r2, "sea", 11, 1, 1)
        s.end_round(r2, 11, 2, 1)

        s.delete_user(11)
        self.assertEqual([r["word"] for r in s.all_guesses(r1)], ["wave"])
        self.assertEqual(s.standings(1), [])
        self.assertEqual(s.standings(2), [])

        s.delete_guild(1)
        self.assertIsNone(s.get_guild(1))
        self.assertIsNone(s.get_round(r1))
        self.assertEqual(s.all_guesses(r1), [])
        self.assertIsNotNone(s.get_guild(2))

    def test_migration_adds_manager_role_column(self):
        import sqlite3
        path = Path(self.tmp.name) / "old.db"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE guilds (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, "
                    "cooldown_min INTEGER NOT NULL DEFAULT 10, hints_per_round INTEGER NOT NULL DEFAULT 3, "
                    "next_round_at INTEGER)")
        old.execute("INSERT INTO guilds (guild_id, channel_id) VALUES (5, 50)")
        old.commit()
        old.close()
        migrated = Store(path)
        self.assertIsNone(migrated.get_guild(5)["manager_role_id"])
        migrated.conn.close()


if __name__ == "__main__":
    unittest.main()
