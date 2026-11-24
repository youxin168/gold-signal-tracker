"""Opt-in Telegram delivery. Registration and consent are verified inside Telegram."""

import logging
import os
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path
from threading import Event

from .config import load_object
from .signal import now_utc, utc
from .store import transaction
from .telegram import (
    NEW_SIGNAL_TTL, SCHEMA as EVENTS_SCHEMA, _credentials, _flush_replies, _new_signal_message,
    _read_channel, _telegram_call, _telegram_request, send_message, verify_public_channel,
)
from .telegram_replies import SCHEMA as THREAD_SCHEMA, destination_key, pending_replies, remember_post

LOG = logging.getLogger(__name__)
PROMPT_TTL = timedelta(minutes=10)
MAX_SUBSCRIPTIONS = 25
RESULTS = {"trade", "fixed"}


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_subscriptions (
        owner INTEGER PRIMARY KEY, chat INTEGER NOT NULL UNIQUE, title TEXT NOT NULL, subscribed_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_subscription_prompts (
        owner INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, expires_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_subscription_cursor (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1), next_update INTEGER NOT NULL
    )""")


def _can_send(member: dict, channel: bool) -> bool:
    return member.get("status") == "creator" or (member.get("status") == "administrator"
        and (not channel or member.get("can_post_messages") is True))


def _destination(token: str, bot: int, chat: int, user: int, primary: int) -> str | None:
    """Require both the recipient's permission to manage the chat and the bot's posting rights."""
    if chat >= 0 or chat == primary:
        return None
    details = _read_channel(token, "getChat", {"chat_id": chat})
    kind = details.get("type")
    if details.get("id") != chat or kind not in ("channel", "group", "supergroup"):
        return None
    owner = _read_channel(token, "getChatMember", {"chat_id": chat, "user_id": user})
    member = _read_channel(token, "getChatMember", {"chat_id": chat, "user_id": bot})
    if not (_can_send(owner, kind == "channel") and _can_send(member, kind == "channel")):
        return None
    title = details.get("title")
    return title.strip()[:120] if isinstance(title, str) and title.strip() else "Telegram destination"


def _show_picker(db: Path, token: str, user: int) -> None:
    first = secrets.randbelow(2**31 - 2) + 1
    now = now_utc()
    with transaction(db) as conn:
        _schema(conn)
        conn.execute("DELETE FROM telegram_subscription_prompts WHERE expires_at <= ?", (utc(now),))
        conn.execute("INSERT OR REPLACE INTO telegram_subscription_prompts VALUES (?, ?, ?)",
                     (user, first, utc(now + PROMPT_TTL)))
    buttons = []
    for offset, channel in enumerate((True, False)):
        rights = dict.fromkeys(("is_anonymous", "can_manage_chat", "can_delete_messages",
                                "can_manage_video_chats", "can_restrict_members", "can_promote_members",
                                "can_change_info", "can_invite_users", "can_post_stories",
                                "can_edit_stories", "can_delete_stories", "can_send_welcome_messages"), False)
        rights["can_manage_chat"] = True
        if channel:
            rights["can_post_messages"] = True
        buttons.append({"text": "Choose channel" if channel else "Choose group", "request_chat": {
            "request_id": first + offset, "chat_is_channel": channel, "bot_is_member": True,
            "user_administrator_rights": rights, "bot_administrator_rights": rights,
        }})
    _telegram_call(token, "sendMessage", {
        "chat_id": user,
        "text": ("Add me as an admin of your channel or group first. For a channel, allow Post Messages.\n\n"
                 "Choosing a destination turns on new XAUUSD test alerts there and replaces your previous destination. "
                 "Only choose a chat whose members expect these alerts. /alerts shows your connection; /stopalerts disconnects it."),
        "reply_markup": {"keyboard": [buttons], "resize_keyboard": True, "one_time_keyboard": True},
    })


def _accept_chat(db: Path, token: str, bot: int, primary: int, user: int, shared: dict) -> str:
    request_id, chat = shared.get("request_id"), shared.get("chat_id")
    if type(request_id) is not int or type(chat) is not int or not -(2**52) <= chat < 0:
        return "That destination was not accepted. Open /connectalerts and try again."
    with transaction(db) as conn:
        _schema(conn)
        prompt = conn.execute("SELECT request_id, expires_at FROM telegram_subscription_prompts WHERE owner = ?", (user,)).fetchone()
    if not prompt or request_id not in (prompt["request_id"], prompt["request_id"] + 1) or prompt["expires_at"] <= utc(now_utc()):
        return "This picker expired. Use /connectalerts to open a new one."
    try:
        title = _destination(token, bot, chat, user, primary)
    except ValueError:
        return "Could not verify that destination. Check that you and the bot are admins, then choose it again."
    if title is None:
        return "That chat cannot be connected. Choose a channel or group you manage, other than the main Signal Tracker channel."
    with transaction(db) as conn:
        occupied = conn.execute("SELECT owner FROM telegram_subscriptions WHERE chat = ?", (chat,)).fetchone()
        current = conn.execute("SELECT chat FROM telegram_subscriptions WHERE owner = ?", (user,)).fetchone()
        if occupied and occupied["owner"] != user:
            return "This destination already has an active connection. It was not changed."
        if not current and conn.execute("SELECT COUNT(*) FROM telegram_subscriptions").fetchone()[0] >= MAX_SUBSCRIPTIONS:
            return "All Telegram connections are currently in use. No changes were made."
        if current is None or current["chat"] != chat:
            conn.execute("""INSERT INTO telegram_subscriptions VALUES (?, ?, ?, ?)
                ON CONFLICT (owner) DO UPDATE SET chat=excluded.chat, title=excluded.title, subscribed_at=excluded.subscribed_at""",
                         (user, chat, title, utc(now_utc())))
        conn.execute("DELETE FROM telegram_subscription_prompts WHERE owner = ?", (user,))
    return f"Connected: {title}. Only new XAUUSD test signals will be posted there. Use /alerts to manage or /stopalerts to disconnect."


def handle_update(db: Path, token: str, bot: int, primary: int, update: dict) -> None:
    message = update.get("message", {})
    if not isinstance(message, dict):
        return
    sender, chat, date = message.get("from") or {}, message.get("chat") or {}, message.get("date")
    user = sender.get("id")
    if (chat.get("type") != "private" or type(user) is not int or not 0 < user < 2**52 or chat.get("id") != user
            or sender.get("is_bot") is not False or type(date) is not int or not 0 <= now_utc().timestamp() - date <= PROMPT_TTL.total_seconds()):
        return
    shared = message.get("chat_shared")
    if isinstance(shared, dict):
        send_message(token, str(user), _accept_chat(db, token, bot, primary, user, shared))
        return
    text = message.get("text") or ""
    if text in ("/connectalerts", "/start connect_alerts"):
        _show_picker(db, token, user)
    elif text == "/stopalerts":
        with transaction(db) as conn:
            _schema(conn)
            conn.execute("DELETE FROM telegram_subscriptions WHERE owner = ?", (user,))
            conn.execute("DELETE FROM telegram_subscription_prompts WHERE owner = ?", (user,))
        send_message(token, str(user), "Your Telegram alerts are off. The main Signal Tracker channel was not changed.")
    elif text in ("/alerts", "/start manage_alerts", "/start"):
        with transaction(db) as conn:
            _schema(conn)
            row = conn.execute("SELECT title FROM telegram_subscriptions WHERE owner = ?", (user,)).fetchone()
        current = f"Connected to: {row['title']}." if row else "No Telegram destination connected."
        send_message(token, str(user), f"{current}\n\n/connectalerts — choose or change a destination\n/stopalerts — disconnect")


def poll_once(db: Path, token: str, bot: int, primary: int) -> None:
    with transaction(db) as conn:
        _schema(conn)
        row = conn.execute("SELECT next_update FROM telegram_subscription_cursor WHERE singleton=1").fetchone()
    offset = row[0] if row else 0
    updates = _telegram_request(token, "getUpdates",
                                {"offset": offset, "limit": 25, "timeout": 0, "allowed_updates": ["message"]}, list)
    for update in updates:
        if not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < offset:
            continue
        # Acknowledge only after handling. Registration and disconnect are idempotent.
        handle_update(db, token, bot, primary, update)
        offset = update["update_id"] + 1
        with transaction(db) as conn:
            conn.execute("INSERT OR REPLACE INTO telegram_subscription_cursor VALUES (1, ?)", (offset,))


def deliver(db: Path, config: Path, token: str, bot: int, primary: int) -> None:
    filters = load_object(config / "telegram-preview.json")
    stamp = now_utc()
    with transaction(db) as conn:
        _schema(conn)
        conn.execute(EVENTS_SCHEMA)
        conn.execute(THREAD_SCHEMA)
        recipients = conn.execute("SELECT owner, chat, subscribed_at FROM telegram_subscriptions ORDER BY owner").fetchall()
    for recipient in recipients:
        chat = recipient["chat"]
        if chat == primary:
            continue
        since = recipient["subscribed_at"]
        with transaction(db) as conn:
            events = conn.execute("""SELECT events.id, events.source, events.style FROM telegram_events events
                JOIN signal_records signals ON events.id = signals.signal_id || ':PENDING'
                LEFT JOIN telegram_preview_threads delivery ON delivery.signal_id = signals.signal_id AND delivery.destination = ?
                WHERE events.event = 'PENDING' AND events.expires_at > ? AND signals.issued_at_utc > ?
                  AND signals.mode = 'LIVE' AND signals.pair = 'XAUUSD' AND delivery.message_id IS NULL
                ORDER BY signals.issued_at_utc LIMIT 20""", (destination_key(str(chat)), utc(stamp), since)).fetchall()
        events = [row for row in events if row["style"] in filters["styles"] and row["source"] in filters["sources"]]
        enabled = RESULTS.intersection(filters["results"])
        if not events and (not enabled or not pending_replies(db, str(chat), enabled, at=stamp, since=since)):
            continue
        try:
            if _destination(token, bot, chat, recipient["owner"], primary) is None:
                continue
            for row in events:
                alert = _new_signal_message(db, row["id"])
                if alert:
                    message_id = send_message(token, str(chat), alert, html=True)
                    with transaction(db) as conn:
                        remember_post(conn, row["id"].removesuffix(":PENDING"), str(chat), message_id)
            if enabled:
                _flush_replies(db, token, str(chat), enabled, since=since)
        except ValueError:
            LOG.warning("One Telegram subscription could not deliver; the main channel is unaffected")


def run_subscription_worker(db: Path, config: Path, stop: Event) -> None:
    """Run only in the opted-in preview scanner; never compete with a Telegram webhook."""
    bot = primary = None
    last_delivery = None
    while not stop.is_set():
        try:
            credentials = _credentials(public_channel=True)
            assert credentials is not None
            token, _ = credentials
            if bot is None or primary is None:
                if _read_channel(token, "getWebhookInfo", {}).get("url"):
                    LOG.warning("Telegram self-service is off because the bot already uses a webhook")
                    return
                primary = verify_public_channel()
                bot = _read_channel(token, "getMe", {}).get("id")
                if type(bot) is not int:
                    raise ValueError("Telegram could not verify the bot identity")
                LOG.info("Telegram self-service is listening for opt-in requests")
            poll_once(db, token, bot, primary)
            now = now_utc()
            if last_delivery is None or now - last_delivery >= NEW_SIGNAL_TTL / 15:
                last_delivery = now
                deliver(db, config, token, bot, primary)
        except (KeyError, OSError, ValueError, sqlite3.Error):
            LOG.warning("Telegram self-service is temporarily unavailable; no credentials or destinations were logged")
            stop.wait(20)
        stop.wait(8)
