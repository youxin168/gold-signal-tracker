import argparse
import os
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from signal_tracker.config import CONFIG_DIR
from signal_tracker.phase5 import run_phase5
from signal_tracker.store import publish, transaction
from signal_tracker.telegram import TelegramNetworkError, enqueue, flush_alerts, send_message, verify_public_channel
from signal_tracker.telegram_format import format_new_signal
from signal_tracker.third_target import SCHEMA as TARGET_SCHEMA
from test_checker import START, sample
from test_strategy_engine import CODE

CHANNEL = {"TELEGRAM_BOT_TOKEN": "123:test-token", "TELEGRAM_CHAT_ID": "@gold_fixture"}


class PreviewTelegramTests(unittest.TestCase):
    def test_gold_price_format_sell_move_and_missing_tp3(self):
        signal = replace(sample("LIVE"), direction="SELL", entry=Decimal("3600.00"), sl=Decimal("3606.00"),
                         tp1=Decimal("3594.00"), tp2=Decimal("3591.00"))
        message = format_new_signal(signal, "Swing <Setup> & Test")
        self.assertIn("XAUUSD SELL", message)
        self.assertIn("Side: <b>SELL</b>\nEntry:", message)
        self.assertIn("Swing &lt;Setup&gt; &amp; Test", message)
        self.assertIn("Entry: <code>3600.00</code>", message)
        self.assertIn("SL: <code>3606.00</code> · 600 pips risk", message)
        self.assertIn("TP2: <code>3591.00</code> · 900 pips · 1.50R", message)
        self.assertIn("TP3: None", message)
        self.assertIn("19:00 ICT", message)

    def test_pending_alert_sends_html_with_copyable_prices_and_suggested_tp3(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=START), \
                patch("signal_tracker.telegram._telegram_call", return_value={"message_id": 101}) as api:
            db = Path(tmp) / "signals.db"
            signal = sample("LIVE")
            with transaction(db) as conn:
                self.assertEqual(publish(conn, signal, CODE[signal.strategy_code]), "Published")
                conn.execute(TARGET_SCHEMA)
                conn.execute("INSERT INTO tp3_watch (signal_id, target) VALUES (?, ?)", (signal.signal_id, "2006.35"))
                enqueue(conn, f"{signal.signal_id}:PENDING", signal.source, signal.style, "PENDING", "Fallback", START)
            flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            api.assert_called_once()
            _, method, payload = api.call_args.args
            self.assertEqual((method, payload["parse_mode"]), ("sendMessage", "HTML"))
            self.assertIn("Side: <b>BUY</b>\nEntry:", payload["text"])
            self.assertIn("TP3: <code>2006.35</code> · 635 pips · 3.18R", payload["text"])
            self.assertEqual(payload["text"].count("<code>"), 5)

    def test_plain_test_message_does_not_parse_markup(self):
        with patch("signal_tracker.telegram._telegram_call", return_value={"message_id": 101}) as api:
            send_message(CHANNEL["TELEGRAM_BOT_TOKEN"], "-123", "<test>")
            self.assertEqual(api.call_args.args[-1], {"chat_id": "-123", "text": "<test>"})

    def test_channel_check_is_read_only_and_requires_post_permission(self):
        details = {"id": -123, "type": "channel", "username": "gold_fixture"}
        admin = {"status": "administrator", "can_post_messages": True}
        with patch.dict(os.environ, CHANNEL, clear=True), patch("signal_tracker.telegram._telegram_call") as api:
            api.side_effect = [details, {"id": 123}, admin]
            self.assertEqual(verify_public_channel(), -123)
            self.assertEqual([c.args[1] for c in api.call_args_list], ["getChat", "getMe", "getChatMember"])
            api.side_effect = [details, {"id": 123}, admin | {"can_post_messages": False}]
            with self.assertRaisesRegex(ValueError, "permission to post"):
                verify_public_channel()
            api.side_effect = [details | {"type": "supergroup"}]
            with self.assertRaisesRegex(ValueError, "not the configured public channel"):
                verify_public_channel()

    def test_public_link_and_channel_id_are_checked_without_posting(self):
        details = {"id": -100456, "type": "channel", "username": "gold_fixture"}
        admin = {"status": "administrator", "can_post_messages": True}
        for saved, sent in (("https://t.me/gold_fixture", "@gold_fixture"), ("gold_fixture", "@gold_fixture"), ("-100456", "-100456")):
            with patch.dict(os.environ, CHANNEL | {"TELEGRAM_CHAT_ID": saved}, clear=True), \
                    patch("signal_tracker.telegram._telegram_call", side_effect=[details, {"id": 123}, admin]) as api:
                self.assertEqual(verify_public_channel(), -100456)
                self.assertEqual(api.call_args_list[0].args[-1], {"chat_id": sent})

    def test_read_only_verification_retries_a_connection_failure(self):
        results = [TelegramNetworkError("Timeout"), {"id": -123, "type": "channel", "username": "gold_fixture"},
                   {"id": 123}, {"status": "administrator", "can_post_messages": True}]
        with patch.dict(os.environ, CHANNEL, clear=True), patch("signal_tracker.telegram.time.sleep") as wait, \
                patch("signal_tracker.telegram._telegram_call", side_effect=results) as api:
            self.assertEqual(verify_public_channel(), -123)
            self.assertEqual([c.args[1] for c in api.call_args_list], ["getChat", "getChat", "getMe", "getChatMember"])
            wait.assert_called_once_with(0.5)

    def test_preview_sends_only_recent_new_signals_from_this_run(self):
        now = START + timedelta(minutes=2)
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=now), \
                patch("signal_tracker.telegram.send_message") as send:
            db = Path(tmp) / "signals.db"
            with transaction(db) as conn:
                enqueue(conn, "prior", "CLD", "INT", "PENDING", "Earlier run", START - timedelta(seconds=1))
                enqueue(conn, "prepare", "CLD", "SCA", "PREPARE", "No signal", START)
                enqueue(conn, "target", "CLD", "SCA", "TP2", "Outcome", START)
                enqueue(conn, "external", "EXT1", "INT", "PENDING", "External", START)
                enqueue(conn, "swing", "OWN", "SWG", "PENDING", "Swing", START)
                enqueue(conn, "scalp", "CLD", "SCA", "PENDING", "Scalp", START)
            for _ in range(2):
                flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            self.assertEqual(send.call_args_list, [
                call(CHANNEL["TELEGRAM_BOT_TOKEN"], "-123", f"XAUUSD · LIVE · PENDING\n{text}\nTesting only. Not financial advice.")
                for text in ("Scalp", "Swing")
            ])

    def test_preview_opt_in_does_not_block_snapshots_on_telegram_failure(self):
        args = argparse.Namespace(command="preview-scanner", config_dir=CONFIG_DIR, strategy=None, once=True)
        with patch.dict(os.environ, {}, clear=True), patch("signal_tracker.phase5.now_utc", return_value=START), \
                patch("signal_tracker.phase5.tick", return_value={"message": "scanned"}), \
                patch("signal_tracker.phase5.make_snapshot", return_value={}), \
                patch("signal_tracker.phase5.atomic_json") as write, \
                patch("signal_tracker.phase5.verify_public_channel", return_value=-123) as check, \
                patch("signal_tracker.phase5.flush_alerts", side_effect=ValueError("Telegram is unavailable")) as flush:
            run_phase5(args)
            check.assert_not_called()
            flush.assert_not_called()
            with patch.dict(os.environ, {"TRACKER_PREVIEW_TELEGRAM": "true"}):
                with self.assertLogs("signal_tracker.phase5", level="WARNING") as logs:
                    run_phase5(args)
            self.assertEqual(write.call_count, 4)
            check.assert_called_once()
            self.assertEqual(flush.call_args.kwargs, {"preview_started": START, "preview_channel_id": -123})
            self.assertIn("Telegram delivery skipped", logs.output[0])
