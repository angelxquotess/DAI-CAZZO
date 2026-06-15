# actions/send_dashboard.py
# Dashboard desktop universale per inviare messaggi cross-platform via TOKEN/API.
#
# Comando vocale: "Jarvis invia un messaggio" -> apre la dashboard.
# La dashboard permette di:
#   - selezionare una o piu' piattaforme (WhatsApp, Telegram, Discord, Instagram)
#   - scansionare TUTTE le chat e mostrare la lista con selezione multipla
#   - scrivere un messaggio e inviarlo a tutti i destinatari selezionati
#
# IMPORTANTE:
# - La GUI PyQt6 viene SEMPRE lanciata in un PROCESSO SEPARATO via
#   subprocess (modulo eseguibile: `python -m actions.send_dashboard`).
#   Questo evita il crash classico "QObject: Cannot create children for
#   a parent that is in a different thread" quando il chiamante e' su
#   un thread asyncio diverso dal main thread Qt.
# - L'invio NON apre mai un'app o un sito: usa esclusivamente API/token:
#     Discord  -> REST API con DISCORD_USER_TOKEN
#     Telegram -> Telethon (MTProto) con session file
#     WhatsApp -> bridge HTTP locale (whatsapp-web.js) con session salvata
#     Instagram-> instagrapi con session file (cookie/token)

from __future__ import annotations
import os
import sys
import json
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

# Carica il file .env dalla root del progetto cosi' DISCORD_USER_TOKEN,
# TELEGRAM_API_ID, TELEGRAM_API_HASH, WHATSAPP_BRIDGE_URL ecc. sono
# disponibili in os.environ anche quando il modulo viene avviato come
# subprocess (python -m actions.send_dashboard).
try:
    from dotenv import load_dotenv  # type: ignore
    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.is_file():
        load_dotenv(_ENV_PATH, override=False)
except Exception:
    pass

PLATFORMS = ["whatsapp", "telegram", "discord", "instagram"]
PLATFORM_LABEL = {
    "whatsapp":  "WhatsApp",
    "telegram":  "Telegram",
    "discord":   "Discord",
    "instagram": "Instagram",
}

WA_BASE = os.environ.get("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:8765")


# ---------------------------------------------------------------------------
# Scansione chat (token / session — niente apertura di app)
# ---------------------------------------------------------------------------

def _scan_whatsapp_chats() -> list[str]:
    try:
        r = requests.get(f"{WA_BASE}/chats", timeout=6)
        if not r.ok:
            return []
        chats = r.json().get("chats") or []
        return [c if isinstance(c, str) else (c.get("name") or "") for c in chats if c]
    except Exception:
        return []


def _telegram_client():
    api_id   = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
        return None
    try:
        from telethon.sync import TelegramClient
    except Exception:
        return None
    try:
        client = TelegramClient(str(Path.home() / ".jarvis_tg"), int(api_id), api_hash)
        client.connect()
        if not client.is_user_authorized():
            client.disconnect()
            return None
        return client
    except Exception:
        return None


def _scan_telegram_chats() -> list[str]:
    client = _telegram_client()
    if client is None:
        return []
    try:
        names = []
        for d in client.iter_dialogs(limit=500):
            n = getattr(d, "name", None) or getattr(d, "title", "")
            if n:
                names.append(n)
        return names
    finally:
        try: client.disconnect()
        except Exception: pass


def _scan_discord_chats() -> list[str]:
    tok = os.environ.get("DISCORD_USER_TOKEN")
    if not tok:
        return []
    headers = {"Authorization": tok}
    names: list[str] = []
    try:
        r = requests.get("https://discord.com/api/v9/users/@me/channels",
                         headers=headers, timeout=10)
        if r.ok:
            for ch in r.json():
                if ch.get("type") == 1:
                    u = (ch.get("recipients") or [{}])[0]
                    label = u.get("global_name") or u.get("username") or ""
                    if label:
                        names.append("DM: " + label)
                elif ch.get("type") == 3:
                    names.append("Gruppo: " + (ch.get("name") or "DM"))
    except Exception:
        pass
    return names


def _instagram_client():
    sess = Path.home() / ".jarvis_ig.json"
    if not sess.is_file():
        return None
    try:
        from instagrapi import Client
    except Exception:
        return None
    try:
        cl = Client()
        cl.load_settings(str(sess))
        return cl
    except Exception:
        return None


def _scan_instagram_chats() -> list[str]:
    cl = _instagram_client()
    if cl is None:
        return []
    try:
        threads = cl.direct_threads(amount=100)
        out = []
        for t in threads:
            users = getattr(t, "users", None) or []
            label = ", ".join((getattr(u, "username", "") for u in users)) or "(thread)"
            out.append(label)
        return out
    except Exception:
        return []


SCANNERS: dict[str, Callable[[], list[str]]] = {
    "whatsapp":  _scan_whatsapp_chats,
    "telegram":  _scan_telegram_chats,
    "discord":   _scan_discord_chats,
    "instagram": _scan_instagram_chats,
}


# ---------------------------------------------------------------------------
# Invio (SOLO via API/token — niente apertura app / sito)
# ---------------------------------------------------------------------------

def _send_whatsapp(recipient: str, text: str) -> str:
    try:
        r = requests.post(f"{WA_BASE}/send",
                          json={"to": recipient, "text": text}, timeout=20)
        if r.ok and r.json().get("ok") is True:
            return f"WhatsApp -> {recipient}: inviato"
        return f"WhatsApp -> {recipient}: bridge non disponibile ({r.status_code})"
    except Exception as e:
        return f"WhatsApp -> {recipient}: errore bridge {e}"


def _send_telegram(recipient: str, text: str) -> str:
    client = _telegram_client()
    if client is None:
        return f"Telegram -> {recipient}: sessione/credenziali assenti"
    try:
        target = None
        # 1) cerca per nome esatto / parziale
        for d in client.iter_dialogs(limit=500):
            n = getattr(d, "name", None) or getattr(d, "title", "")
            if n and recipient.lower() in n.lower():
                target = d.entity
                if n.lower() == recipient.lower():
                    break
        # 2) prova come username diretto (@x)
        if target is None:
            try:
                target = client.get_entity(recipient)
            except Exception:
                target = None
        if target is None:
            return f"Telegram -> {recipient}: chat non trovata"
        client.send_message(target, text)
        return f"Telegram -> {recipient}: inviato"
    except Exception as e:
        return f"Telegram -> {recipient}: errore {e}"
    finally:
        try: client.disconnect()
        except Exception: pass


def _send_discord(recipient: str, text: str) -> str:
    tok = os.environ.get("DISCORD_USER_TOKEN")
    if not tok:
        return f"Discord -> {recipient}: DISCORD_USER_TOKEN non impostato"
    headers = {"Authorization": tok, "Content-Type": "application/json"}
    channel_id: str | None = None
    try:
        if recipient.isdigit():
            channel_id = recipient
        else:
            label = recipient.split(":", 1)[-1].strip().lower()
            # cerca tra DM esistenti
            r = requests.get("https://discord.com/api/v9/users/@me/channels",
                             headers=headers, timeout=10)
            if r.ok:
                for ch in r.json():
                    if ch.get("type") == 1:
                        u = (ch.get("recipients") or [{}])[0]
                        name = (u.get("global_name") or u.get("username") or "").lower()
                        if name == label:
                            channel_id = ch.get("id")
                            break
        if not channel_id:
            return f"Discord -> {recipient}: canale non trovato"
        r = requests.post(
            f"https://discord.com/api/v9/channels/{channel_id}/messages",
            headers=headers, json={"content": text}, timeout=15,
        )
        if r.ok:
            return f"Discord -> {recipient}: inviato"
        return f"Discord -> {recipient}: HTTP {r.status_code}"
    except Exception as e:
        return f"Discord -> {recipient}: errore {e}"


def _send_instagram(recipient: str, text: str) -> str:
    cl = _instagram_client()
    if cl is None:
        return f"Instagram -> {recipient}: sessione assente"
    try:
        username = recipient.lstrip("@").split(",")[0].strip()
        user_id = cl.user_id_from_username(username)
        cl.direct_send(text, user_ids=[user_id])
        return f"Instagram -> {recipient}: inviato"
    except Exception as e:
        return f"Instagram -> {recipient}: errore {e}"


def _dispatch(platform: str, recipient: str, text: str) -> str:
    p = (platform or "").lower()
    if p == "whatsapp":  return _send_whatsapp(recipient, text)
    if p == "telegram":  return _send_telegram(recipient, text)
    if p == "discord":   return _send_discord(recipient, text)
    if p == "instagram": return _send_instagram(recipient, text)
    return f"{platform}/{recipient}: piattaforma non supportata"


def send_to_targets(targets: list[tuple[str, str]], text: str,
                    on_log: Callable[[str], None] | None = None) -> list[str]:
    out: list[str] = []
    for platform, recipient in targets:
        try:
            r = _dispatch(platform, recipient, text)
        except Exception as e:
            r = f"{platform}/{recipient}: errore {e}"
        out.append(r)
        if on_log:
            try: on_log(r)
            except Exception: pass
    return out


# ---------------------------------------------------------------------------
# CLI fallback (no GUI / modalita' headless)
# ---------------------------------------------------------------------------

def _open_dashboard_cli(initial_text: str = "") -> list[str]:
    print("\n=== JARVIS: Dashboard Invio Messaggi (CLI) ===\n")
    print("Piattaforme: " + ", ".join(PLATFORM_LABEL.values()))
    raw = input("Quali piattaforme? (whatsapp,telegram,discord,instagram) > ").strip()
    chosen = [p.strip().lower() for p in raw.split(",") if p.strip() in PLATFORMS]
    if not chosen:
        print("Nessuna piattaforma valida.")
        return []
    targets: list[tuple[str, str]] = []
    for p in chosen:
        print(f"\n--- Scansione {PLATFORM_LABEL[p]}...")
        names = SCANNERS[p]()
        if not names:
            r = input(f"  (nessuna chat) destinatario manuale {PLATFORM_LABEL[p]} > ").strip()
            if r: targets.append((p, r))
            continue
        for i, n in enumerate(names, 1):
            print(f"  {i:3d}. {n}")
        picks = input(f"Indici per {PLATFORM_LABEL[p]} (es. 1,3,7) > ").strip()
        for tok in picks.split(","):
            tok = tok.strip()
            if tok.isdigit():
                idx = int(tok) - 1
                if 0 <= idx < len(names):
                    targets.append((p, names[idx]))
    if not targets:
        print("Nessun destinatario selezionato.")
        return []
    text = initial_text or input("\nMessaggio > ").strip()
    if not text:
        print("Messaggio vuoto, annullo.")
        return []
    print(f"\nInvio a {len(targets)} destinatari...")
    return send_to_targets(targets, text, on_log=lambda s: print("  " + s))


# ---------------------------------------------------------------------------
# GUI PyQt6 — eseguita SEMPRE in un processo separato (entry point __main__)
# ---------------------------------------------------------------------------

def _run_gui_in_this_process(initial_text: str = "") -> int:
    """Costruisce e mostra la dashboard nel processo CORRENTE.
    Da usare SOLO se siamo il processo subprocess (entry point del modulo).
    Ritorna l'exit code dell'app."""
    try:
        from PyQt6.QtCore import Qt, QThread, pyqtSignal
        from PyQt6.QtWidgets import (
            QApplication, QDialog, QVBoxLayout, QHBoxLayout, QCheckBox,
            QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
            QGroupBox, QSplitter,
        )
    except Exception as e:
        print(f"[Dashboard] PyQt6 non disponibile: {e}")
        _open_dashboard_cli(initial_text)
        return 0

    app = QApplication.instance() or QApplication(sys.argv)

    class ScanThread(QThread):
        done = pyqtSignal(str, list)
        def __init__(self, platform: str):
            super().__init__()
            self.platform = platform
        def run(self):
            try:    names = SCANNERS[self.platform]()
            except Exception: names = []
            self.done.emit(self.platform, names)

    class SendThread(QThread):
        progress = pyqtSignal(str)
        finished_all = pyqtSignal(list)
        def __init__(self, targets, text):
            super().__init__()
            self.targets, self.text = targets, text
        def run(self):
            logs = send_to_targets(self.targets, self.text,
                                   on_log=lambda s: self.progress.emit(s))
            self.finished_all.emit(logs)

    dlg = QDialog(None)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.setWindowTitle("JARVIS - Invia messaggio")
    dlg.resize(960, 640)
    dlg.setStyleSheet("""
        QDialog { background:#0f1115; color:#e6e6e6;
                  font-family:'Segoe UI', sans-serif; font-size:13px; }
        QGroupBox { border:1px solid #2a2f3a; border-radius:8px;
                    margin-top:12px; padding:8px; }
        QGroupBox::title { color:#7fdfff; padding:0 6px; }
        QCheckBox { padding:3px; }
        QPushButton { background:#1f6feb; color:white; border:none;
                      padding:8px 14px; border-radius:6px; }
        QPushButton:hover { background:#2f7fff; }
        QPushButton:disabled { background:#2a2f3a; color:#888; }
        QListWidget, QTextEdit { background:#161a22; border:1px solid #2a2f3a;
                                 border-radius:6px; color:#e6e6e6; padding:4px; }
        QLabel { color:#e6e6e6; }
    """)

    main_lay = QVBoxLayout(dlg)

    plat_box = QGroupBox("Piattaforme (selezione multipla)")
    plat_lay = QHBoxLayout(plat_box)
    plat_checks: dict[str, QCheckBox] = {}
    for p in PLATFORMS:
        cb = QCheckBox(PLATFORM_LABEL[p])
        plat_checks[p] = cb
        plat_lay.addWidget(cb)
    plat_lay.addStretch(1)
    btn_scan = QPushButton("Scansiona chat")
    plat_lay.addWidget(btn_scan)
    main_lay.addWidget(plat_box)

    split = QSplitter(Qt.Orientation.Horizontal)
    main_lay.addWidget(split, 1)

    lists_box = QGroupBox("Destinatari (selezione multipla)")
    lists_lay = QVBoxLayout(lists_box)
    chats_lists: dict[str, QListWidget] = {}
    labels_map: dict[str, QLabel] = {}
    for p in PLATFORMS:
        lbl = QLabel(PLATFORM_LABEL[p] + " - nessuna scansione")
        lbl.setStyleSheet("color:#7fdfff; padding-top:6px;")
        lw  = QListWidget()
        lw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        lw.setVisible(False)
        lbl.setVisible(False)
        chats_lists[p] = lw
        labels_map[p] = lbl
        lists_lay.addWidget(lbl)
        lists_lay.addWidget(lw)
    lists_lay.addStretch(1)
    split.addWidget(lists_box)

    msg_box = QGroupBox("Messaggio")
    msg_lay = QVBoxLayout(msg_box)
    msg_edit = QTextEdit()
    msg_edit.setPlainText(initial_text)
    msg_edit.setPlaceholderText("Scrivi qui il messaggio da inviare a tutti i destinatari selezionati...")
    msg_lay.addWidget(msg_edit, 1)
    log_view = QTextEdit()
    log_view.setReadOnly(True)
    log_view.setMaximumHeight(170)
    log_view.setPlaceholderText("Log invio...")
    msg_lay.addWidget(log_view)
    btn_row = QHBoxLayout()
    btn_send = QPushButton("INVIA")
    btn_cancel = QPushButton("Chiudi")
    btn_row.addStretch(1)
    btn_row.addWidget(btn_cancel)
    btn_row.addWidget(btn_send)
    msg_lay.addLayout(btn_row)
    split.addWidget(msg_box)
    split.setSizes([420, 540])

    dlg._threads = []

    def on_scan():
        wanted = [p for p, cb in plat_checks.items() if cb.isChecked()]
        if not wanted:
            log_view.append("Seleziona almeno una piattaforma.")
            return
        btn_scan.setEnabled(False)
        log_view.append("Scansione: " + ", ".join(PLATFORM_LABEL[p] for p in wanted) + "...")
        remaining = [len(wanted)]
        for p in wanted:
            labels_map[p].setText(PLATFORM_LABEL[p] + " - scansione in corso...")
            labels_map[p].setVisible(True)
            chats_lists[p].setVisible(True)
            chats_lists[p].clear()
            t = ScanThread(p)
            def _done(plat_id, names):
                lst = chats_lists[plat_id]
                lblw = labels_map[plat_id]
                if not names:
                    lblw.setText(PLATFORM_LABEL[plat_id] + " - nessuna chat (verifica token/session)")
                else:
                    lblw.setText(f"{PLATFORM_LABEL[plat_id]} - {len(names)} chat")
                    for n in names:
                        QListWidgetItem(n, lst)
                remaining[0] -= 1
                if remaining[0] <= 0:
                    btn_scan.setEnabled(True)
            t.done.connect(_done)
            t.start()
            dlg._threads.append(t)

    def on_send():
        text = msg_edit.toPlainText().strip()
        if not text:
            log_view.append("Inserisci il testo del messaggio.")
            return
        targets: list[tuple[str, str]] = []
        for p, lw in chats_lists.items():
            for it in lw.selectedItems():
                targets.append((p, it.text()))
        if not targets:
            log_view.append("Seleziona almeno un destinatario.")
            return
        btn_send.setEnabled(False)
        log_view.append(f"Invio a {len(targets)} destinatari...")
        st = SendThread(targets, text)
        st.progress.connect(lambda s: log_view.append(s))
        def _fin(_logs):
            log_view.append("--- Fatto ---")
            btn_send.setEnabled(True)
        st.finished_all.connect(_fin)
        st.start()
        dlg._threads.append(st)

    btn_scan.clicked.connect(on_scan)
    btn_send.clicked.connect(on_send)
    btn_cancel.clicked.connect(dlg.close)

    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return app.exec()


# ---------------------------------------------------------------------------
# Entry point pubblico
# ---------------------------------------------------------------------------

def open_dashboard(initial_text: str = "", prefer_gui: bool = True) -> None:
    """Apre la dashboard SENZA bloccare JARVIS.

    Strategia:
      - Lancia il modulo come subprocess (`python -m actions.send_dashboard`)
        passando il testo iniziale tramite variabile d'ambiente.
      - In questo modo la GUI vive in un processo separato con il proprio
        QApplication sul main thread Qt e non puo' crashare JARVIS anche
        se chiamata da un worker thread asyncio.
      - Se PyQt6 non e' installato nel subprocess o non c'e' display,
        il modulo cade automaticamente in modalita' CLI nello stesso
        subprocess (non blocca JARVIS).
    """
    env = dict(os.environ)
    env["JARVIS_DASHBOARD_INITIAL_TEXT"] = initial_text or ""
    env["JARVIS_DASHBOARD_PREFER_GUI"]   = "1" if prefer_gui else "0"

    # Trova la root del progetto (parent di actions/)
    project_root = Path(__file__).resolve().parent.parent

    try:
        creationflags = 0
        kwargs = {}
        if sys.platform.startswith("win"):
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            creationflags = 0x00000008 | 0x00000200
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "actions.send_dashboard"],
            cwd=str(project_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as e:
        # Fallback: avvia la GUI in un thread separato di QUESTO processo
        # (puo' fallire su alcuni setup, ma non blocca JARVIS).
        print(f"[Dashboard] subprocess fallito ({e}), fallback CLI in thread.")
        threading.Thread(
            target=lambda: _open_dashboard_cli(initial_text),
            daemon=True,
        ).start()


def _main_entry() -> int:
    initial = os.environ.get("JARVIS_DASHBOARD_INITIAL_TEXT", "")
    prefer_gui = os.environ.get("JARVIS_DASHBOARD_PREFER_GUI", "1") == "1"
    if not prefer_gui:
        _open_dashboard_cli(initial)
        return 0
    try:
        return _run_gui_in_this_process(initial)
    except Exception as e:
        print(f"[Dashboard] errore GUI: {e}")
        _open_dashboard_cli(initial)
        return 0


if __name__ == "__main__":
    sys.exit(_main_entry())
