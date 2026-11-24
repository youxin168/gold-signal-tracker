"""Prospective Telegram notifications. Bot credentials are never persisted."""

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import load_object
from .signal import now_utc, utc
from .store import from_record, transaction
from .telegram_format import format_new_signal
from .telegram_replies import acknowledge_reply, pending_replies, remember_post

LOG = logging.getLogger(__name__)
EVENTS = {"PREPARE", "PENDING", "ACTIVE", "TP1", "TP2", "TP2_OPEN", "TP3", "SL", "BE", "EXPIRED"}
NEW_SIGNAL_TTL = timedelta(minutes=15)
SCHEMA = """CREATE TABLE IF NOT EXISTS telegram_events (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, style TEXT NOT NULL, event TEXT NOT NULL,
    message TEXT NOT NULL, expires_at TEXT NOT NULL, settled_at TEXT
)"""


class NoRedirect(HTTPRedirectHandler):
    """Do not follow unsolicited redirects carrying the Telegram token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TelegramNetworkError(ValueError):
    """The Telegram request could not be confirmed at the network level."""


def enqueue(connection: sqlite3.Connection, event_id: str, source: str, style: str,
            event: str, text: str, at: datetime) -> None:
    connection.execute(SCHEMA)
    lifetime = NEW_SIGNAL_TTL if event in {"PREPARE", "PENDING", "ACTIVE", "TP1", "TP2_OPEN"} else timedelta(hours=24)
    connection.execute("INSERT OR IGNORE INTO telegram_events VALUES (?, ?, ?, ?, ?, ?, NULL)",
                       (event_id, source, style, event, f"XAUUSD · LIVE · {event}\n{text}\nTesting only. Not financial advice.",
                        utc(at + lifetime)))


def _telegram_request(token: str, method: str, payload: dict, result_type: type):
    # Do not log URLs, responses or exceptions that could contain credentials or chat IDs.
    request = Request(f"https://api.telegram.org/bot{token}/{method}",
                      data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(NoRedirect).open(request, timeout=12) as response:
            data = json.load(response)
            if data.get("ok") is not True or not isinstance(data.get("result"), result_type):
                raise ValueError("Unexpected Telegram response")
            return data["result"]
    except HTTPError as error:
        raise ValueError(f"Telegram returned HTTP {error.code}; check token, chat permissions or limits") from None
    except (URLError, TimeoutError, OSError) as error:
        reason = error.reason if isinstance(error, URLError) else error
        # The exception text may contain the tokenized URL. Log only its type.
        raise TelegramNetworkError(f"Telegram {method} connection failed ({type(reason).__name__})") from None
    except (UnicodeError, ValueError, AttributeError):
        raise ValueError(f"Telegram did not acknowledge {method}") from None


def _telegram_call(token: str, method: str, payload: dict) -> dict:
    return _telegram_request(token, method, payload, dict)


def _read_channel(token: str, method: str, payload: dict) -> dict:
    # These read-only requests are safe to retry immediately. Never wrap sendMessage.
    for delay in (0.5, 1.5):
        try:
            return _telegram_call(token, method, payload)
        except TelegramNetworkError:
            time.sleep(delay)
    return _telegram_call(token, method, payload)


def send_message(token: str, chat: str, text: str, *, html: bool = False, reply_to: int | None = None) -> int:
    payload: dict = {"chat_id": chat, "text": text}
    if html:
        payload["parse_mode"] = "HTML"
    if reply_to is not None:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": False}
    message_id = _telegram_call(token, "sendMessage", payload).get("message_id")
    if type(message_id) is not int or message_id <= 0:
        raise ValueError("Telegram did not return a usable message ID")
    return message_id


def _credentials(*, public_channel: bool = False) -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token and not chat and not public_channel:
        return None
    if not token or not chat:
        missing = "TELEGRAM_BOT_TOKEN" if not token else "TELEGRAM_CHAT_ID"
        raise ValueError(f"{missing} is not available to the runner")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("TELEGRAM_BOT_TOKEN must be the full bot token from BotFather")
    if public_channel:
        link = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)/?", chat, re.IGNORECASE)
        if link:
            chat = f"@{link[1]}"
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", chat):
            chat = f"@{chat}"
        if not re.fullmatch(r"@[A-Za-z0-9_]+|-100\d+", chat):
            raise ValueError("TELEGRAM_CHAT_ID must be the public channel @username, t.me link, or numeric channel ID")
    elif not re.fullmatch(r"-?\d+|@[A-Za-z0-9_]+", chat):
        raise ValueError("TELEGRAM_CHAT_ID must be a numeric chat ID or public channel handle")
    return token, chat


def verify_public_channel() -> int:
    """Check the destination and posting rights without sending a message."""
    credentials = _credentials(public_channel=True)
    assert credentials is not None
    token, chat = credentials
    details = _read_channel(token, "getChat", {"chat_id": chat})
    handle = details.get("username")
    channel_id = details.get("id")
    if (details.get("type") != "channel" or not isinstance(handle, str)
            or not handle or type(channel_id) is not int
            or chat.casefold() not in {f"@{handle}".casefold(), str(channel_id)}):
        raise ValueError("Telegram destination is not the configured public channel")
    bot = _read_channel(token, "getMe", {}).get("id")
    if type(bot) is not int:
        raise ValueError("Telegram did not identify the bot")
    member = _read_channel(token, "getChatMember", {"chat_id": channel_id, "user_id": bot})
    if member.get("status") != "administrator" or member.get("can_post_messages") is not True:
        raise ValueError("Add the bot to the channel as an administrator with permission to post")
    return channel_id


def _new_signal_message(db: Path, event_id: str) -> str | None:
    signal_id = event_id.removesuffix(":PENDING")
    with transaction(db) as connection:
        row = connection.execute(
            """SELECT signal_records.*, versions.specification FROM signal_records JOIN versions USING (strategy_code)
               WHERE signal_id = ? AND mode = 'LIVE' AND pair = 'XAUUSD'""", (signal_id,)
        ).fetchone()
        if row is None:
            return None
        signal, _ = from_record(row)
        name = json.loads(row["specification"]).get("name") or signal.strategy_code
        watch = None
        if signal.tp3 is None and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tp3_watch'"
        ).fetchone():
            watch = connection.execute("SELECT target FROM tp3_watch WHERE signal_id = ?", (signal_id,)).fetchone()
        return format_new_signal(signal, name, Decimal(watch["target"]) if watch else None)


def flush_alerts(db: Path, config_dir: Path, *, preview_started: datetime | None = None,
                 preview_channel_id: int | None = None) -> None:
    credentials = _credentials(public_channel=preview_started is not None)
    if credentials is None:
        print("Telegram is not enabled; no messages sent.")
        return
    token, chat = credentials
    if preview_started is not None:
        if preview_channel_id is None:
            raise ValueError("The Telegram public channel was not verified")
        chat = str(preview_channel_id)
    if not db.exists():
        print("No signal records exist; no alerts to send.")
        return
    config_name = "telegram.json" if preview_started is None else "telegram-preview.json"
    filters = load_object(config_dir / config_name)
    allowed = {"styles": {"SCA", "INT", "SWG"}, "sources": {"CLD", "EXT1", "EXT2", "OWN"}, "events": EVENTS}
    for key, values in allowed.items():
        items = filters.get(key)
        if not isinstance(items, list) or any(not isinstance(item, str) or item not in values for item in items):
            raise ValueError(f"Check Telegram {key} filter in config/{config_name}")
    results = filters.get("results", []) if preview_started is not None else []
    if not isinstance(results, list) or any(item not in ("trade", "fixed") for item in results):
        raise ValueError(f"Check Telegram results filter in config/{config_name}")
    with transaction(db) as connection:
        connection.execute(SCHEMA)
        events = connection.execute(
            "SELECT * FROM telegram_events WHERE settled_at IS NULL ORDER BY expires_at, id"
        ).fetchall()
    for row in events:
        at = utc(now_utc())
        posted = None
        # PENDING rows have a fixed TTL; use it to recover the enqueue time without
        # changing the journal schema. Preview never sends events from prior runs.
        preview_ok = (preview_started is None or (
            row["event"] == "PENDING" and row["expires_at"] >= utc(preview_started + NEW_SIGNAL_TTL)))
        if (row["expires_at"] > at and row["style"] in filters["styles"]
                and row["source"] in filters["sources"] and row["event"] in filters["events"] and preview_ok):
            rich_message = _new_signal_message(db, row["id"]) if row["event"] == "PENDING" else None
            if rich_message is None:
                send_message(token, chat, row["message"])
            else:
                posted = send_message(token, chat, rich_message, html=True)
            LOG.info("Telegram acknowledged %s alert", row["event"])
        # Each acknowledgement is committed separately so an error on a later alert does not resend it.
        with transaction(db) as connection:
            if preview_started is not None and posted is not None:
                remember_post(connection, row["id"].removesuffix(":PENDING"), chat, posted)
            connection.execute("UPDATE telegram_events SET settled_at = ? WHERE id = ?", (at, row["id"]))
    if results:
        _flush_replies(db, token, chat, set(results))


def _flush_replies(db: Path, token: str, chat: str, enabled: set[str], *, since: str | None = None) -> None:
    failures = set()
    first_error = None
    for reply in pending_replies(db, chat, enabled, at=now_utc(), since=since):
        # If the official reply fails, don't post Fixed-SL ahead of it.
        if reply.signal_id in failures:
            continue
        try:
            send_message(token, chat, reply.text, html=True, reply_to=reply.message_id)
        except ValueError as error:
            first_error = first_error or error
            failures.add(reply.signal_id)
            continue
        acknowledge_reply(db, chat, reply)
        LOG.info("Telegram acknowledged %s final result reply", reply.kind)
    if first_error is not None:
        raise first_error
