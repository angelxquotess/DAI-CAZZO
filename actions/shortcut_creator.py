"""actions/shortcut_creator.py

Sistema di SCORCIATOIE per JARVIS.

L'utente puo' dire:
    "jarvis crea scorciatoia"
        -> nome:        "ricerca tonno"
        -> cosa fare:   "ricerca tonno fresco"
    "jarvis crea scorciatoia"
        -> nome:        "apri chatgpt"
        -> cosa fare:   "apri chatgpt"
    "jarvis crea scorciatoia"
        -> nome:        "avvia gioco"
        -> cosa fare:   "avvia un file C:/Games/MyGame.exe"

Per ogni scorciatoia viene generato un file Python autonomo dentro la
cartella `scorciatoie/<slug>.py` contenente la funzione `run()` che
esegue il comando.

Inoltre viene mantenuto un registro JSON in `scorciatoie/_index.json`
con tutte le scorciatoie disponibili (per consultazione rapida e per il
comando "jarvis esegui scorciatoia <nome>").
"""

from __future__ import annotations

import json
import os
import re
import sys
import platform
import subprocess
import webbrowser
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


SHORTCUTS_DIR = _base_dir() / "scorciatoie"
INDEX_FILE    = SHORTCUTS_DIR / "_index.json"


def _slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_\- ]+", "", s)
    s = re.sub(r"[\s\-]+", "_", s)
    return s or "scorciatoia"


def _ensure_dirs():
    SHORTCUTS_DIR.mkdir(parents=True, exist_ok=True)
    init = SHORTCUTS_DIR / "__init__.py"
    if not init.exists():
        init.write_text("# scorciatoie generate da Jarvis\n", encoding="utf-8")


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"shortcuts": {}}
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"shortcuts": {}}


def _save_index(idx: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------
# Classificazione del comando "cosa deve fare"
# ---------------------------------------------------------------
_SEARCH_KWS = ("cerca", "ricerca", "ricerca su google", "googla", "trova ", "cerca su")
_CHATGPT_KWS = ("chatgpt", "chat gpt", "openai chat", "apri chatgpt", "vai su chatgpt")
_OPENAPP_KWS = ("apri ", "lancia ", "avvia app ", "avvia applicazione", "esegui app ")
_OPENFILE_KWS = ("avvia ", "esegui ", "apri file ", "lancia file ", "avvia file ")
_URL_RE = re.compile(r"^(https?://\S+)$", re.IGNORECASE)


def _classify_action(text: str) -> dict:
    t = (text or "").strip()
    tl = t.lower()

    if not t:
        return {"kind": "noop", "raw": text}

    # URL diretto
    if _URL_RE.match(t):
        return {"kind": "open_url", "url": t}

    # ChatGPT
    if any(k in tl for k in _CHATGPT_KWS):
        return {"kind": "open_url", "url": "https://chat.openai.com/"}

    # Ricerca su Google (Firefox)
    for kw in _SEARCH_KWS:
        if tl.startswith(kw):
            q = t[len(kw):].strip(" :,.")
            return {"kind": "search", "query": q or t}
    if "ricerca" in tl or "cerca" in tl:
        # rimuovi parola "ricerca/cerca" e usa il resto
        q = re.sub(r"^(cerca|ricerca|googla)\b[:\s]*", "", tl).strip()
        return {"kind": "search", "query": q or t}

    # Apri / lancia file (path)
    for kw in _OPENFILE_KWS:
        if kw in tl:
            target = t.split(kw, 1)[1].strip().strip('"').strip("'")
            if target and (os.path.sep in target or "/" in target or target.lower().endswith(
                    (".exe", ".bat", ".cmd", ".sh", ".lnk", ".app", ".py", ".ps1"))):
                return {"kind": "run_file", "path": target}

    # Path "raw" (anche senza keyword): es. "C:\\Users\\...\\file.bat"
    stripped = t.strip().strip('"').strip("'")
    if stripped.lower().endswith(
            (".exe", ".bat", ".cmd", ".sh", ".lnk", ".app", ".py", ".ps1")):
        return {"kind": "run_file", "path": stripped}
    if re.match(r"^[A-Za-z]:[\\/]", stripped) or stripped.startswith("/"):
        return {"kind": "run_file", "path": stripped}

    # Apri app per nome
    for kw in _OPENAPP_KWS:
        if tl.startswith(kw):
            app_name = t[len(kw):].strip()
            return {"kind": "open_app", "app_name": app_name}

    # Generico: prova run_file se sembra un path
    if os.path.sep in t and Path(t).exists():
        return {"kind": "run_file", "path": t}

    # Fallback: trattalo come query di ricerca
    return {"kind": "search", "query": t}


# ---------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------
def _render_shortcut_code(name: str, slug: str, action: dict) -> str:
    kind = action.get("kind")
    header = (
        f'"""Scorciatoia auto-generata da Jarvis.\n'
        f'\n'
        f'    Nome     : {name}\n'
        f'    Slug     : {slug}\n'
        f'    Tipo     : {kind}\n'
        f'    Creata il: {datetime.now().isoformat(timespec="seconds")}\n'
        f'"""\n'
        f'import os, sys, subprocess, webbrowser, urllib.parse, platform\n\n'
    )

    if kind == "search":
        q = action.get("query", "")
        body = (
            f'def run():\n'
            f'    url = "https://www.google.com/search?q=" + urllib.parse.quote({q!r})\n'
            f'    # Apri SEMPRE su Firefox quando possibile\n'
            f'    try:\n'
            f'        webbrowser.get("firefox").open(url)\n'
            f'        return f"Cerco {q!r} su Firefox."\n'
            f'    except Exception:\n'
            f'        webbrowser.open(url)\n'
            f'        return f"Cerco {q!r} sul browser di default."\n'
        )
    elif kind == "open_url":
        u = action.get("url", "")
        body = (
            f'def run():\n'
            f'    try:\n'
            f'        webbrowser.get("firefox").open({u!r})\n'
            f'        return "Apro {u} su Firefox."\n'
            f'    except Exception:\n'
            f'        webbrowser.open({u!r})\n'
            f'        return "Apro {u} sul browser di default."\n'
        )
    elif kind == "run_file":
        # Normalizza il path: usa forward-slash (validi anche su Windows)
        # e poi codificalo con json.dumps per garantire l'assenza di
        # sequenze unicode-escape rotte (\U, \N, \x...).
        p = action.get("path", "")
        p_norm = p.replace("\\", "/")
        path_literal = json.dumps(p_norm, ensure_ascii=False)
        body = (
            f'def run():\n'
            f'    path = {path_literal}\n'
            f'    if not os.path.exists(path):\n'
            f'        return f"File non trovato: {{path}}"\n'
            f'    ext = os.path.splitext(path)[1].lower()\n'
            f'    try:\n'
            f'        if platform.system() == "Windows":\n'
            f'            if ext in (".bat", ".cmd"):\n'
            f'                # I .bat hanno bisogno di shell=True / cmd /c\n'
            f'                subprocess.Popen(["cmd", "/c", path],\n'
            f'                                 cwd=os.path.dirname(path) or None,\n'
            f'                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))\n'
            f'            elif ext == ".ps1":\n'
            f'                subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass",\n'
            f'                                  "-File", path])\n'
            f'            elif ext == ".py":\n'
            f'                subprocess.Popen([sys.executable, path])\n'
            f'            else:\n'
            f'                os.startfile(path)\n'
            f'        elif platform.system() == "Darwin":\n'
            f'            subprocess.Popen(["open", path])\n'
            f'        else:\n'
            f'            subprocess.Popen(["xdg-open", path])\n'
            f'        return f"Eseguo {{path}}."\n'
            f'    except Exception as e:\n'
            f'        return f"Errore avviando {{path}}: {{e}}"\n'
        )
    elif kind == "open_app":
        a = action.get("app_name", "")
        body = (
            f'def run():\n'
            f'    app = {a!r}\n'
            f'    # Tentativo 1: chiama il modulo open_app del progetto\n'
            f'    try:\n'
            f'        from actions.open_app import open_app\n'
            f'        return open_app(parameters={{"app_name": app}})\n'
            f'    except Exception as e:\n'
            f'        # Tentativo 2: avvio diretto\n'
            f'        try:\n'
            f'            if platform.system() == "Windows":\n'
            f'                subprocess.Popen(["start", "", app], shell=True)\n'
            f'            else:\n'
            f'                subprocess.Popen([app])\n'
            f'            return f"Apro {{app}}."\n'
            f'        except Exception as e2:\n'
            f'            return f"Impossibile aprire {{app}}: {{e2}}"\n'
        )
    else:
        body = (
            'def run():\n'
            '    return "Scorciatoia vuota: nessuna azione configurata."\n'
        )

    main_block = (
        '\n\nif __name__ == "__main__":\n'
        '    print(run())\n'
    )
    return header + body + main_block


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------
def create_shortcut(parameters: Optional[dict] = None,
                    response=None, player=None, session_memory=None) -> str:
    """Crea (o sovrascrive) una scorciatoia.

    parameters:
        name:    nome scorciatoia (es. "ricerca tonno")
        action:  cosa deve fare in linguaggio naturale
                 (es. "cerca tonno fresco", "apri chatgpt",
                  "avvia C:/Games/X.exe")
    """
    params = parameters or {}
    name   = (params.get("name")   or "").strip()
    action_text = (params.get("action") or params.get("do") or "").strip()

    if not name:
        return "Capo, dimmi il nome della scorciatoia."
    if not action_text:
        return f"Capo, cosa deve fare la scorciatoia '{name}'?"

    _ensure_dirs()
    slug = _slugify(name)
    if not slug:
        return "Nome scorciatoia non valido."

    action = _classify_action(action_text)
    code = _render_shortcut_code(name, slug, action)

    target = SHORTCUTS_DIR / f"{slug}.py"
    target.write_text(code, encoding="utf-8")

    # Update index
    idx = _load_index()
    idx.setdefault("shortcuts", {})[slug] = {
        "name":   name,
        "file":   f"scorciatoie/{slug}.py",
        "action": action,
        "raw":    action_text,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_index(idx)

    if player:
        try:
            player.write_log(f"SYS: shortcut created -> {name} ({slug})")
        except Exception:
            pass

    return (f"Scorciatoia '{name}' creata in scorciatoie/{slug}.py "
            f"(tipo: {action.get('kind')}).")


def list_shortcuts(parameters=None, **_) -> str:
    _ensure_dirs()
    idx = _load_index()
    items = idx.get("shortcuts", {})
    if not items:
        return "Nessuna scorciatoia ancora creata, capo."
    lines = ["Scorciatoie disponibili:"]
    for slug, meta in items.items():
        lines.append(f" - {meta.get('name', slug)} [{slug}] -> {meta.get('action', {}).get('kind')}")
    return "\n".join(lines)


def run_shortcut(parameters: Optional[dict] = None,
                 response=None, player=None, session_memory=None) -> str:
    """Esegue una scorciatoia esistente per nome o slug."""
    params = parameters or {}
    name = (params.get("name") or params.get("slug") or "").strip()
    if not name:
        return "Capo, quale scorciatoia devo eseguire?"

    _ensure_dirs()
    idx = _load_index()
    items = idx.get("shortcuts", {})

    # match per slug esatto
    slug = _slugify(name)
    meta = items.get(slug)

    # fallback: match parziale per name
    if meta is None:
        for s, m in items.items():
            if name.lower() in (m.get("name") or "").lower():
                slug, meta = s, m
                break

    if meta is None:
        return f"Scorciatoia '{name}' non trovata."

    path = SHORTCUTS_DIR / f"{slug}.py"
    if not path.exists():
        return f"Il file della scorciatoia '{name}' non esiste piu'."

    # import dinamico e chiama run()
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"scorciatoie.{slug}", path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore
        if hasattr(mod, "run"):
            return str(mod.run() or f"Eseguita scorciatoia '{meta.get('name')}'.")
        return "La scorciatoia non espone la funzione run()."
    except Exception as e:
        return f"Errore eseguendo la scorciatoia: {e}"


if __name__ == "__main__":
    # quick self-test
    print(create_shortcut({"name": "ricerca tonno", "action": "cerca tonno fresco"}))
    print(list_shortcuts())
    print(run_shortcut({"name": "ricerca tonno"}))
