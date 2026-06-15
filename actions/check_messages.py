# actions/check_messages.py
# Comando "Jarvis ho messaggi da leggere?" + poller di notifiche per
# WhatsApp / Telegram / Discord / Instagram.
#
# Quando un nuovo messaggio viene rilevato:
#   1) viene chiamato `speak(...)` per annunciare vocalmente "Nuovo messaggio
#      <piattaforma> da <mittente>".
#   2) il mittente viene salvato in `message_state.set_last_incoming(...)`
#      cosi' che il comando "rispondi con <testo>" sappia su quale
#      piattaforma e a chi rispondere.

from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from typing import Callable

import requests

# Carica il file .env della root del progetto cosi' i token (Discord,
# Telegram, WhatsApp) sono visibili anche nei thread poller.
try:
    from dotenv import load_dotenv  # type: ignore
    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.is_file():
        load_dotenv(_ENV_PATH, override=False)
except Exception:
    pass

from actions.message_state import set_last_incoming


WA_BASE = os.environ.get("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:8765")


# ---------------------------------------------------------------------------
# Snapshot non-letti (per il comando "ho messaggi?")
# ---------------------------------------------------------------------------

def _unread_whatsapp() -> list[dict]:
    try:
        r = requests.get(f"{WA_BASE}/unread", timeout=4)
        if not r.ok:
            return []
        return [
            {"from": m.get("from", ""), "body": m.get("body", "")}
            for m in r.json().get("messages", [])
        ]
    except Exception:
        return []


def _unread_telegram() -> list[dict]:
    try:
        api_id   = os.environ.get("TELEGRAM_API_ID")
        api_hash = os.environ.get("TELEGRAM_API_HASH")
        if not (api_id and api_hash):
            return []
        from telethon.sync import TelegramClient
        client = TelegramClient(str(Path.home() / ".jarvis_tg"), int(api_id), api_hash)
        client.connect()
        if not client.is_user_authorized():
            client.disconnect()
            return []
        out = []
        for d in client.iter_dialogs(limit=200):
            unread = getattr(d, "unread_count", 0) or 0
            if unread <= 0:
                continue
            name = getattr(d, "name", None) or getattr(d, "title", "")
            last = ""
            try:
                m = getattr(d, "message", None)
                if m is not None:
                    last = (getattr(m, "text", "") or "")[:120]
            except Exception:
                pass
            out.append({"from": name, "count": unread, "body": last})
        client.disconnect()
        return out
    except Exception:
        return []


def _unread_discord() -> list[dict]:
    """Discord non espone read-state pubblicamente: prendiamo gli ultimi
    messaggi dei DM e li mostriamo come 'recenti'."""
    try:
        tok = os.environ.get("DISCORD_USER_TOKEN")
        if not tok:
            return []
        headers = {"Authorization": tok}
        out = []
        r = requests.get("https://discord.com/api/v9/users/@me/channels",
                         headers=headers, timeout=6)
        if not r.ok:
            return []
        for ch in r.json()[:10]:
            if ch.get("type") != 1:
                continue
            ch_id = ch.get("id")
            u = (ch.get("recipients") or [{}])[0]
            name = u.get("global_name") or u.get("username") or "DM"
            try:
                mr = requests.get(
                    f"https://discord.com/api/v9/channels/{ch_id}/messages?limit=1",
                    headers=headers, timeout=6,
                )
                if mr.ok and mr.json():
                    msg = mr.json()[0]
                    out.append({"from": name, "body": (msg.get("content") or "")[:120]})
            except Exception:
                continue
        return out
    except Exception:
        return []


def _unread_instagram() -> list[dict]:
    try:
        sess = Path.home() / ".jarvis_ig.json"
        if not sess.is_file():
            return []
        from instagrapi import Client
        cl = Client()
        cl.load_settings(str(sess))
        threads = cl.direct_threads(amount=20)
        out = []
        for t in threads:
            try:
                if not getattr(t, "is_seen", True):
                    users = getattr(t, "users", None) or []
                    label = ", ".join((getattr(u, "username", "") for u in users)) or "(thread)"
                    last = ""
                    msgs = getattr(t, "messages", None) or []
                    if msgs:
                        last = (getattr(msgs[0], "text", "") or "")[:120]
                    out.append({"from": label, "body": last})
            except Exception:
                continue
        return out
    except Exception:
        return []


def gather_unread() -> dict:
    return {
        "whatsapp":  _unread_whatsapp(),
        "telegram":  _unread_telegram(),
        "discord":   _unread_discord(),
        "instagram": _unread_instagram(),
    }


def summarize_unread(data: dict | None = None) -> str:
    data = data or gather_unread()
    parts = []
    total = 0
    for plat, items in data.items():
        if not items:
            continue
        n = sum(int(it.get("count", 1)) for it in items)
        total += n
        names = ", ".join((it.get("from", "") or "?") for it in items[:5])
        parts.append(f"{plat.capitalize()}: {n} ({names})")
    if not parts:
        return "Nessun messaggio non letto, signore."
    return "Hai " + str(total) + " messaggi non letti - " + " | ".join(parts)


def check_messages(parameters: dict | None = None, response=None,
                   player=None, session_memory=None) -> str:
    data = gather_unread()
    text = summarize_unread(data)
    if player and hasattr(player, "write_log"):
        try:
            player.write_log("[messages] " + text)
        except Exception:
            pass
    return text


# ---------------------------------------------------------------------------
# Poller di notifiche
# ---------------------------------------------------------------------------

_started = False
_lock = threading.Lock()


def _notify(speak: Callable[[str], None],
            on_new_message: Callable[[str, str], None] | None,
            platform: str, sender: str) -> None:
    """Annuncia vocalmente e aggiorna lo stato condiviso."""
    if not sender:
        return
    try:
        set_last_incoming(platform, sender)
    except Exception:
        pass
    try:
        plat_label = platform.capitalize()
        speak(f"Signore, nuovo messaggio {plat_label} da {sender}")
    except Exception:
        pass
    if on_new_message:
        try:
            on_new_message(platform, sender)
        except Exception:
            pass


def _poll_whatsapp(speak, on_new_message) -> None:
    last_ids: set[str] = set()
    first_pass = True
    while True:
        try:
            r = requests.get(f"{WA_BASE}/unread", timeout=8)
            if r.ok:
                for m in r.json().get("messages", []):
                    mid = m.get("id") or (m.get("from", "") + "|" + (m.get("body", "")[:40]))
                    if mid in last_ids:
                        continue
                    last_ids.add(mid)
                    if len(last_ids) > 300:
                        last_ids = set(list(last_ids)[-150:])
                    if first_pass:
                        continue  # non annunciare lo stato iniziale
                    _notify(speak, on_new_message, "whatsapp", m.get("from", "") or "qualcuno")
            first_pass = False
        except Exception:
            pass
        time.sleep(10)


def _poll_discord(speak, on_new_message) -> None:
    tok = os.environ.get("DISCORD_USER_TOKEN")
    if not tok:
        return
    headers = {"Authorization": tok}
    last_ids: dict[str, str] = {}
    first_pass = True
    while True:
        try:
            r = requests.get("https://discord.com/api/v9/users/@me/channels",
                             headers=headers, timeout=8)
            if r.ok:
                for ch in r.json()[:15]:
                    if ch.get("type") != 1:
                        continue
                    ch_id = ch.get("id")
                    u = (ch.get("recipients") or [{}])[0]
                    name = u.get("global_name") or u.get("username") or "DM"
                    try:
                        mr = requests.get(
                            f"https://discord.com/api/v9/channels/{ch_id}/messages?limit=1",
                            headers=headers, timeout=8,
                        )
                        if mr.ok and mr.json():
                            msg = mr.json()[0]
                            mid = msg.get("id", "")
                            prev = last_ids.get(ch_id)
                            last_ids[ch_id] = mid
                            if prev and prev != mid and not first_pass:
                                # ignora messaggi inviati da me stesso (heuristic)
                                author = (msg.get("author") or {})
                                # se l'autore e' il destinatario del DM e' il "loro"
                                if author.get("id") != msg.get("recipient_id"):
                                    _notify(speak, on_new_message, "discord", name)
                    except Exception:
                        continue
            first_pass = False
        except Exception:
            pass
        time.sleep(15)


def _poll_telegram(speak, on_new_message) -> None:
    api_id   = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
        return
    try:
        from telethon import TelegramClient, events
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(str(Path.home() / ".jarvis_tg"), int(api_id), api_hash, loop=loop)

        @client.on(events.NewMessage(incoming=True))
        async def _handler(event):
            try:
                sender = await event.get_sender()
                name = (getattr(sender, "first_name", "") or
                        getattr(sender, "username", "") or
                        getattr(sender, "title", "") or
                        "qualcuno")
                _notify(speak, on_new_message, "telegram", name)
            except Exception:
                pass

        client.start()
        client.run_until_disconnected()
    except Exception:
        pass


def _poll_instagram(speak, on_new_message) -> None:
    sess = Path.home() / ".jarvis_ig.json"
    if not sess.is_file():
        return
    last_ids: dict[str, str] = {}
    first_pass = True
    while True:
        try:
            from instagrapi import Client
            cl = Client()
            cl.load_settings(str(sess))
            threads = cl.direct_threads(amount=20) or []
            for t in threads:
                tid = getattr(t, "id", None) or getattr(t, "thread_id", None)
                if not tid:
                    continue
                msgs = getattr(t, "messages", None) or []
                last_msg = msgs[0] if msgs else None
                mid = getattr(last_msg, "id", None) if last_msg else None
                prev = last_ids.get(tid)
                last_ids[tid] = mid or ""
                if mid and prev and prev != mid and not first_pass:
                    users = getattr(t, "users", None) or []
                    label = ", ".join((getattr(u, "username", "") for u in users)) or "qualcuno"
                    # ignora messaggi miei
                    try:
                        my_id = cl.user_id
                        if getattr(last_msg, "user_id", None) and str(last_msg.user_id) == str(my_id):
                            continue
                    except Exception:
                        pass
                    _notify(speak, on_new_message, "instagram", label)
            first_pass = False
        except Exception:
            pass
        time.sleep(20)


def start_notification_pollers(
    speak: Callable[[str], None],
    on_new_message: Callable[[str, str], None] | None = None,
) -> None:
    """Avvia i poller in thread daemon. Idempotente."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_poll_whatsapp,  args=(speak, on_new_message), daemon=True).start()
    threading.Thread(target=_poll_discord,   args=(speak, on_new_message), daemon=True).start()
    threading.Thread(target=_poll_telegram,  args=(speak, on_new_message), daemon=True).start()
    threading.Thread(target=_poll_instagram, args=(speak, on_new_message), daemon=True).start()
