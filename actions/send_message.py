# actions/send_message.py
# Punto di ingresso UNICO per inviare messaggi.
# Tutti i vecchi metodi di invio basati su pyautogui / apertura di app /
# apertura di siti sono stati RIMOSSI. L'invio avviene SOLO via API/token
# (Discord user token, Telegram MTProto session, WhatsApp Web bridge,
# Instagram session di instagrapi). Vedi actions/send_dashboard.py.

from __future__ import annotations
from typing import Any

from actions.send_dashboard import (
    open_dashboard,
    send_to_targets,
)
from actions.message_state import get_last_incoming


def send_message(parameters: dict | None = None,
                 response: Any = None,
                 player: Any = None,
                 session_memory: Any = None) -> str:
    """
    Comando 'jarvis invia un messaggio'.

    Comportamento:
      - Se l'utente ha specificato sia il destinatario che la piattaforma
        e il testo: invia direttamente via API (nessuna app aperta).
      - Altrimenti apre la DASHBOARD desktop (PyQt6) dove l'utente
        sceglie piattaforme, scansiona le chat, seleziona destinatari e
        scrive il messaggio.
      - Caso speciale "rispondi con <testo>": se receiver/platform non
        sono dati ma c'e' un ultimo messaggio in arrivo memorizzato,
        usa quello come destinatario.
    """
    params       = parameters or {}
    receiver     = (params.get("receiver")     or "").strip()
    message_text = (params.get("message_text") or "").strip()
    platform     = (params.get("platform")     or "").strip().lower()

    # Caso "rispondi con": platform vuota o "reply" + receiver vuoto.
    if not receiver and message_text and (not platform or platform in ("reply", "rispondi")):
        last = get_last_incoming()
        if last:
            platform, receiver = last

    direct = bool(receiver and message_text and platform and
                  platform not in ("dashboard", "panel", "ask", "choose"))

    if direct:
        results = send_to_targets([(platform, receiver)], message_text)
        msg = results[0] if results else "Nessun risultato."
        if player and hasattr(player, "write_log"):
            try:
                player.write_log("[msg] " + msg)
            except Exception:
                pass
        return msg

    # Apri la dashboard desktop. NON blocca.
    try:
        open_dashboard(initial_text=message_text)
        return "Dashboard messaggi aperta, signore."
    except Exception as e:
        return f"Impossibile aprire la dashboard messaggi: {e}"
