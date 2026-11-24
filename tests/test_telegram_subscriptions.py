import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from signal_tracker.config import CONFIG_DIR
from signal_tracker.signal import utc
from signal_tracker.store import publish, transaction
from signal_tracker.telegram import enqueue
from signal_tracker.telegram_replies import destination_key
from signal_tracker.telegram_subscriptions import (
    _accept_chat, _destination, _schema, _show_picker, deliver, handle_update, poll_once,
)
from test_checker import START, sample
from test_strategy_engine import CODE

MODULE = "signal_tracker.telegram_subscriptions"


class TelegramSubscriptionTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "signals.db"
        clock = patch(f"{MODULE}.now_utc", return_value=START)
        clock.start()
        self.addCleanup(clock.stop)

    def prompt(self, user=5):
        with transaction(self.db) as conn:
            _schema(conn)
            conn.execute("INSERT INTO telegram_subscription_prompts VALUES (?, 70, ?)", (user, utc(START + timedelta(minutes=5))))

    def subscribers(self):
        with transaction(self.db) as conn:
            _schema(conn)
            return [(row["owner"], row["chat"]) for row in conn.execute("SELECT owner, chat FROM telegram_subscriptions")]

    def test_telegram_picker_requires_admin_rights_and_uses_one_time_ids(self):
        with patch(f"{MODULE}._telegram_call") as api:
            _show_picker(self.db, "test", 5)
        payload = api.call_args.args[2]
        channel, group = (item["request_chat"] for item in payload["reply_markup"]["keyboard"][0])
        self.assertEqual(payload["chat_id"], 5)
        self.assertTrue(channel["chat_is_channel"])
        self.assertTrue(channel["bot_administrator_rights"]["can_post_messages"])
        self.assertFalse(group["chat_is_channel"])
        self.assertNotEqual(channel["request_id"], group["request_id"])

    def test_only_both_admins_can_connect_and_main_channel_is_blocked(self):
        post_admin = {"status": "administrator", "can_post_messages": True}
        details = {"id": -100, "type": "channel", "title": "Example"}
        with patch(f"{MODULE}._read_channel", side_effect=[details, {"status": "creator"}, post_admin]) as api:
            self.assertIsNone(_destination("test", 44, -1, 5, -1))
            api.assert_not_called()
            self.assertEqual(_destination("test", 44, -100, 5, -1), "Example")
        with patch(f"{MODULE}._read_channel", side_effect=[details, {"status": "member"}, post_admin]):
            self.assertIsNone(_destination("test", 44, -100, 5, -1))
        with patch(f"{MODULE}._read_channel", side_effect=[details, post_admin, {"status": "administrator"}]):
            self.assertIsNone(_destination("test", 44, -100, 5, -1))

    def test_switch_is_per_account_and_chat_cannot_be_claimed_twice(self):
        with patch(f"{MODULE}._destination", return_value="Example"):
            self.assertIn("expired", _accept_chat(self.db, "test", 44, -1, 5, {"chat_id": -100, "request_id": 70}))
            self.prompt(5)
            self.prompt(6)
            self.assertIn("Connected", _accept_chat(self.db, "test", 44, -1, 5, {"chat_id": -100, "request_id": 70}))
            self.assertIn("already", _accept_chat(self.db, "test", 44, -1, 6, {"chat_id": -100, "request_id": 70}))
            self.prompt(5)
            self.assertIn("Connected", _accept_chat(self.db, "test", 44, -1, 5, {"chat_id": -200, "request_id": 71}))
        self.assertEqual(self.subscribers(), [(5, -200)])

    def test_poll_ignores_group_commands_and_disconnects_only_authenticated_sender(self):
        with transaction(self.db) as conn:
            _schema(conn)
            conn.executemany("INSERT INTO telegram_subscriptions VALUES (?, ?, 'Example', ?)",
                             [(5, -100, utc(START)), (6, -200, utc(START))])
        message = {"from": {"id": 5, "is_bot": False}, "date": int(START.timestamp()), "text": "/stopalerts"}
        updates = [
            {"update_id": 10, "message": message | {"chat": {"id": -100, "type": "group"}}},
            {"update_id": 11, "message": message | {"chat": {"id": 5, "type": "private"}}},
        ]
        with patch(f"{MODULE}._telegram_request", side_effect=[updates, []]) as api, patch(f"{MODULE}.send_message") as send:
            poll_once(self.db, "test", 44, -1)
            poll_once(self.db, "test", 44, -1)
        send.assert_called_once()
        self.assertEqual(self.subscribers(), [(6, -200)])
        self.assertEqual(api.call_args.args[2]["offset"], 12)

    def test_stale_and_forged_private_updates_do_not_change_settings(self):
        message = {"chat": {"id": 6, "type": "private"}, "from": {"id": 5, "is_bot": False},
                   "date": int(START.timestamp()), "text": "/connectalerts"}
        with patch(f"{MODULE}._show_picker") as picker:
            handle_update(self.db, "test", 44, -1, {"message": message})
            message["chat"]["id"] = 5
            message["date"] -= 601
            handle_update(self.db, "test", 44, -1, {"message": message})
        picker.assert_not_called()

    def test_delivers_only_post_subscription_once_even_if_main_channel_already_settled(self):
        signal = sample("LIVE")
        with transaction(self.db) as conn:
            _schema(conn)
            self.assertEqual(publish(conn, signal, CODE[signal.strategy_code]), "Published")
            enqueue(conn, f"{signal.signal_id}:PENDING", signal.source, signal.style, "PENDING", "Text", START)
            conn.execute("UPDATE telegram_events SET settled_at = ?", (utc(START),))
            conn.executemany("INSERT INTO telegram_subscriptions VALUES (?, ?, 'Example', ?)", [
                (5, -100, utc(START - timedelta(minutes=1))),
                (6, -200, utc(START)),
                (7, -1, utc(START - timedelta(minutes=1))),
            ])
        with patch(f"{MODULE}._destination", return_value="Example"), patch(f"{MODULE}.send_message", return_value=101) as send:
            deliver(self.db, CONFIG_DIR, "test", 44, -1)
            deliver(self.db, CONFIG_DIR, "test", 44, -1)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], "-100")
        self.assertIn("<code>", send.call_args.args[2])
        with transaction(self.db) as conn:
            self.assertEqual(conn.execute("SELECT destination FROM telegram_preview_threads").fetchone()[0], destination_key("-100"))


if __name__ == "__main__":
    unittest.main()
