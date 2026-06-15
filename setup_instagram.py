# setup_instagram.py
# Helper INTERATTIVO da eseguire UNA SOLA VOLTA per loggare l'account
# Instagram con `instagrapi` e generare il file di sessione che JARVIS
# usera' per sempre (cookie + device fingerprint, niente piu' password).
#
# Uso:
#     python setup_instagram.py
#
# Al termine viene creato `~/.jarvis_ig.json`. Da quel momento la
# dashboard JARVIS scansiona le chat e invia messaggi via Instagram
# senza alcun login, in background.

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

SESSION_PATH = Path.home() / ".jarvis_ig.json"


def main() -> int:
    print("=" * 60)
    print(" JARVIS - Setup Instagram (una sola volta)")
    print("=" * 60)
    print(f" Sessione di destinazione: {SESSION_PATH}")
    print()

    if SESSION_PATH.is_file():
        ans = input("Esiste gia' una sessione. Sovrascrivere? [y/N] ").strip().lower()
        if ans != "y":
            print("Annullato.")
            return 0

    try:
        from instagrapi import Client
        from instagrapi.exceptions import (
            BadPassword, ChallengeRequired, TwoFactorRequired,
        )
    except ImportError:
        print("ERROR: instagrapi non installato. Esegui:")
        print("    pip install instagrapi")
        return 1

    username = input("Username Instagram: ").strip()
    if not username:
        print("Username vuoto.")
        return 1
    password = getpass.getpass("Password (non viene salvata): ")

    cl = Client()
    print("\nLogin in corso...")

    try:
        cl.login(username, password)
    except TwoFactorRequired:
        code = input("Codice 2FA: ").strip()
        cl.login(username, password, verification_code=code)
    except BadPassword:
        print("Password errata.")
        return 1
    except ChallengeRequired:
        print("Instagram chiede una verifica (challenge). Apri l'app, "
              "conferma il login e ri-esegui questo script.")
        return 1
    except Exception as e:
        print(f"Login fallito: {e}")
        return 1

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(str(SESSION_PATH))

    # piccolo sanity check
    try:
        info = cl.account_info()
        who = getattr(info, "username", username)
        print(f"\nOK: loggato come @{who}")
    except Exception:
        print("\nOK: sessione salvata (sanity check saltato).")

    print(f"Sessione scritta in: {SESSION_PATH}")
    print("\nDa adesso JARVIS usera' SOLO questo file - niente piu' "
          "username/password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
