import os
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from signal_tracker import parallel_targets
from signal_tracker.automation import GAPS_SQL
from signal_tracker.config import CONFIG_DIR
from signal_tracker.signal import Outcome, Status
from signal_tracker.store import publish, save_outcome, transaction
from signal_tracker.telegram import enqueue, flush_alerts
from signal_tracker.telegram_format import format_trade_result
from test_checker import START, sample
from test_preview_telegram import CHANNEL
from test_strategy_engine import CODE


def setup_signal(db: Path, at=START, signal_id="one"):
    signal = replace(sample("LIVE"), signal_id=signal_id, issued_at_utc=at, setup_closed_at_utc=at,
                     recorded_at=at, expires_at_utc=at + timedelta(minutes=4))
    with transaction(db) as conn:
        assert publish(conn, signal, CODE[signal.strategy_code]) == "Published"
        parallel_targets.create(conn, signal, D("2006"))
        enqueue(conn, f"{signal_id}:PENDING", signal.source, signal.style, "PENDING", "New signal", at)
    return signal


def save_trade_and_fixed(db: Path, phase: str, statuses: tuple[str, ...], gap=None):
    closed = START + timedelta(minutes=2)
    with transaction(db) as conn:
        save_outcome(conn, "one", Outcome(Status.TP2, closed_at=closed, result_r=D("1.48")))
        parallel_targets.save(conn, "one",
                              parallel_targets.TargetPlan((D("2002"), D("2004"), D("2006")), statuses, phase, closed), gap)


class TelegramResultRepliesTests(unittest.TestCase):
    def test_reply_chain_survives_restart_and_closures_are_not_resent(self):
        later = START + timedelta(minutes=5)
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=later), \
                patch("signal_tracker.telegram._telegram_call", side_effect=[
                    {"message_id": 141}, {"message_id": 142}, {"message_id": 143}
                ]) as api:
            db = Path(tmp) / "signals.db"
            old = setup_signal(db, START - timedelta(minutes=1), "older")
            setup_signal(db)
            with transaction(db) as conn:
                save_outcome(conn, old.signal_id, Outcome(Status.SL, closed_at=later, result_r=D("-1.02")))
            flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            self.assertEqual(api.call_count, 1)
            save_trade_and_fixed(db, "ACTIVE", ("TP", "TP", "OPEN"))
            flush_alerts(db, CONFIG_DIR, preview_started=later, preview_channel_id=-123)
            self.assertEqual(api.call_count, 2)
            trade = api.call_args.args[-1]
            self.assertIn("CLOSED AT TP2", trade["text"])
            self.assertIn("Trade result: +1.48R", trade["text"])
            self.assertEqual(trade["reply_parameters"], {"message_id": 141, "allow_sending_without_reply": False})
            save_trade_and_fixed(db, "CLOSED", ("TP", "TP", "SL"))
            flush_alerts(db, CONFIG_DIR, preview_started=later, preview_channel_id=-999)
            self.assertEqual(api.call_count, 2)  # Never reuse a message ID in a different channel.
            flush_alerts(db, CONFIG_DIR, preview_started=later, preview_channel_id=-123)
            fixed = api.call_args.args[-1]
            self.assertEqual(fixed["reply_parameters"], trade["reply_parameters"])
            self.assertIn("TP3 order: stopped at <code>1998</code> · <b>-1.00R</b>", fixed["text"])
            self.assertIn("Combined: +2.00R</b> · +0.67R vs. total starting risk", fixed["text"])
            flush_alerts(db, CONFIG_DIR, preview_started=later, preview_channel_id=-123)
            self.assertEqual(api.call_count, 3)

    def test_gap_and_failed_official_reply_delay_results(self):
        later = START + timedelta(minutes=5)
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=later), \
                patch("signal_tracker.telegram._telegram_call", return_value={"message_id": 121}) as api:
            db = Path(tmp) / "signals.db"
            setup_signal(db)
            flush = lambda: flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            flush()
            save_trade_and_fixed(db, "CLOSED", ("TP", "TP", "TP"))
            with transaction(db) as conn:
                conn.execute(GAPS_SQL)
                conn.execute("INSERT INTO signal_gaps VALUES ('one', 'Missing minute')")
            flush()
            self.assertEqual(api.call_count, 1)
            with transaction(db) as conn:
                conn.execute("DELETE FROM signal_gaps WHERE signal_id='one'")
            api.side_effect = ValueError("Telegram delivery unavailable")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                flush()
            self.assertEqual(api.call_count, 2)
            api.side_effect = None
            flush()
            self.assertEqual(api.call_count, 4)
            messages = [call.args[-1]["text"] for call in api.call_args_list[-2:]]
            self.assertIn("CLOSED AT TP2", messages[0])
            self.assertIn("FIXED-SL FINAL RESULT", messages[1])

    def test_expired_is_unfilled_and_breakeven_preserves_partial_r(self):
        signal = sample("LIVE")
        expired = format_trade_result(signal, "Test", Outcome(Status.EXPIRED, closed_at=signal.expires_at_utc))
        self.assertIn("Not filled · No R result", expired)
        partial = format_trade_result(signal, "Test", Outcome(Status.BE, closed_at=START, result_r=D("0.45")))
        self.assertIn("remainder stopped at breakeven", partial)
        self.assertIn("Trade result: +0.45R", partial)
        self.assertIsNone(format_trade_result(signal, "Test", Outcome(Status.TP1, result_r=D("0.45"))))

    def test_expiry_sends_one_not_filled_reply_without_fixed_result(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=START) as clock, \
                patch("signal_tracker.telegram._telegram_call", return_value={"message_id": 151}) as api:
            db = Path(tmp) / "signals.db"
            signal = setup_signal(db)
            flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            clock.return_value = signal.expires_at_utc
            with transaction(db) as conn:
                save_outcome(conn, signal.signal_id, Outcome(Status.EXPIRED, closed_at=signal.expires_at_utc))
                parallel_targets.save(conn, signal.signal_id, parallel_targets.TargetPlan(
                    (signal.tp1, signal.tp2, D("2006")), ("EXPIRED",) * 3, "EXPIRED", signal.expires_at_utc), None)
            for _ in range(2):
                flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            self.assertEqual(api.call_count, 2)
            payload = api.call_args.args[-1]
            self.assertIn("EXPIRED", payload["text"])
            self.assertIn("Not filled · No R result", payload["text"])
            self.assertEqual(payload["reply_parameters"]["message_id"], 151)

    def test_missing_price_warning_is_once_per_post_and_recovery_still_sends_results(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, CHANNEL, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=START) as clock, \
                patch("signal_tracker.telegram._telegram_call", return_value={"message_id": 151}) as api:
            db = Path(tmp) / "signals.db"
            setup_signal(db)
            flush = lambda: flush_alerts(db, CONFIG_DIR, preview_started=START, preview_channel_id=-123)
            flush()
            with transaction(db) as conn:
                conn.execute(GAPS_SQL)
                conn.execute("INSERT INTO signal_gaps VALUES ('one', 'Missing minute')")
            clock.return_value = START + timedelta(minutes=5)
            flush()
            self.assertEqual(api.call_count, 1)
            clock.return_value = START + timedelta(hours=1)
            flush()
            self.assertEqual(api.call_count, 2)
            notice = api.call_args.args[-1]
            self.assertIn("RESULT UNCONFIRMED", notice["text"])
            self.assertEqual(notice["reply_parameters"]["message_id"], 151)
            flush()
            self.assertEqual(api.call_count, 2)
            with transaction(db) as conn:
                conn.execute("DELETE FROM signal_gaps WHERE signal_id='one'")
            save_trade_and_fixed(db, "CLOSED", ("TP", "TP", "SL"))
            flush()
            self.assertEqual(api.call_count, 4)
