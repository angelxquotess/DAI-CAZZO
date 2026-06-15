# actions/message_state.py
# Stato condiviso fra i poller di notifiche e il comando "rispondi con ...".
#
# Quando un poller (WhatsApp / Telegram / Discord / Instagram) riceve un
# nuovo messaggio chiama set_last_incoming(platform, sender). L'UI parla
# l'annuncio vocale e ricorda l'ultimo mittente per piattaforma. Quando
# l'utente dice "rispondi con <testo>" il main.py legge get_last_incoming()
# e instrada via il send_message della dashboard (API/token, niente
# apertura app).

from __future__ import annotations
import threading
from typing import Callable, Optional

_lock = threading.Lock()
_last_incoming: Optional[tuple[str, str]] = None   # (platform, sender)
_last_per_platform: dict[str, str] = {}
_listeners: list[Callable[[str, str], None]] = []


def set_last_incoming(platform: str, sender: str) -> None:
    global _last_incoming
    if not platform or not sender:
        return
    with _lock:
        _last_incoming = (platform, sender)
        _last_per_platform[platform] = sender
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(platform, sender)
        except Exception:
            pass


def get_last_incoming() -> Optional[tuple[str, str]]:
    with _lock:
        return _last_incoming


def get_last_for_platform(platform: str) -> Optional[str]:
    with _lock:
        return _last_per_platform.get(platform)


def register_listener(cb: Callable[[str, str], None]) -> None:
    """Registra una callback chiamata ad ogni nuovo messaggio in arrivo.
    Idempotente."""
    with _lock:
        if cb not in _listeners:
            _listeners.append(cb)


def clear_last_incoming() -> None:
    global _last_incoming
    with _lock:
        _last_incoming = None
