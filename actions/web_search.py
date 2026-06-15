# web_search.py
# RICERCA WEB SU FIREFOX (stile jarvis_offline.py)
#
# Apre la ricerca SEMPRE su Firefox usando l'URL Google.
# Se Firefox non e' disponibile, fallback al browser di default.

import os
import sys
import shutil
import platform
import subprocess
import urllib.parse
import webbrowser


# ---------------------------------------------------------------
# Firefox finder (Windows + cross-platform)
# ---------------------------------------------------------------
def _find_firefox_path() -> str | None:
    """Trova l'eseguibile di Firefox sul sistema."""
    # 1) PATH lookup
    candidate = shutil.which("firefox") or shutil.which("firefox.exe")
    if candidate:
        return candidate

    # 2) Path tipici Windows
    if platform.system() == "Windows":
        win_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe"),
        ]
        for p in win_paths:
            if p and os.path.exists(p):
                return p

    # 3) Path tipici macOS / Linux
    mac_path = "/Applications/Firefox.app/Contents/MacOS/firefox"
    if os.path.exists(mac_path):
        return mac_path
    for p in ("/usr/bin/firefox", "/usr/local/bin/firefox", "/snap/bin/firefox"):
        if os.path.exists(p):
            return p

    return None


def _open_firefox(url: str) -> bool:
    """Apre l'URL specificato in Firefox. Restituisce True se ce l'ha fatta."""
    # Tentativo 1: webbrowser.get("firefox")
    try:
        b = webbrowser.get("firefox")
        if b.open(url):
            return True
    except Exception:
        pass

    # Tentativo 2: eseguibile diretto
    path = _find_firefox_path()
    if path:
        try:
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [path, url],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            print(f"[WebSearch] errore lancio firefox: {e}")

    # Fallback: browser di default
    try:
        return webbrowser.open(url)
    except Exception:
        return False


# ---------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------
def web_search(
    parameters: dict | None = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Esegue una ricerca aprendo Firefox sulla pagina Google dei risultati.

    Comportamento (stile jarvis_offline.py):
        url = "https://www.google.com/search?q=" + quote(query)
        webbrowser.open(url)   # -> ma su FIREFOX
    """
    params = parameters or {}
    query = (params.get("query") or "").strip()
    items = params.get("items", []) or []
    mode  = (params.get("mode") or "search").lower().strip()

    if not query and items:
        query = " vs ".join(items)
        mode = "compare"

    if not query:
        return "Please provide a search query, sir."

    if player:
        try:
            player.write_log(f"[Search] {query}")
        except Exception:
            pass

    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    print(f"[WebSearch] Firefox -> {url}")

    ok = _open_firefox(url)
    if ok:
        return f"Cerco '{query}' su Google con Firefox, signore."
    return f"Non sono riuscito ad aprire Firefox per cercare '{query}'."
