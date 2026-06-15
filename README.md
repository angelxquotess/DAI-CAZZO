# JARVIS — Unified Messaging Edition

Assistente vocale JARVIS (Windows) con un **unico comando di
messaggistica cross-platform** che funziona via TOKEN/API/SESSIONE —
**senza mai aprire un'app o un sito web**, tutto in background.

> Forkato dal Mark XXXIX-OR di FatihMakes. Questa edizione rimuove
> tutti i vecchi comandi di invio (pyautogui, browser, finestre) e li
> sostituisce con UNA SOLA dashboard desktop (PyQt6) + notifiche vocali
> + risposta automatica via voce.

---

## Cosa fa

### 1. Comando vocale UNICO: `"Jarvis invia un messaggio"`
Apre una **dashboard desktop** (PyQt6) dove puoi:

1. **scegliere l'app** (una o piu' fra WhatsApp, Telegram, Discord, Instagram);
2. **scansionare tutte le chat** della piattaforma (lista a selezione multipla);
3. **selezionare i destinatari**;
4. **scrivere il messaggio**;
5. premere **INVIA** → il messaggio parte su TUTTI i destinatari selezionati
   in parallelo, **senza aprire alcuna app o sito**.

La dashboard gira in un **processo separato** (`subprocess.Popen`) con il
suo `QApplication` sul main thread Qt: questo elimina il classico crash
`QObject: Cannot create children for a parent that is in a different
thread` che si presentava quando la finestra veniva creata dal worker
thread asyncio di JARVIS.

### 2. Notifiche vocali in entrata su TUTTE le piattaforme
Al boot, JARVIS avvia in background:

- un **listener event-driven** Telethon su Telegram (zero polling);
- **poller periodici** per WhatsApp (`/unread` del bridge), Discord
  (`/users/@me/channels`), Instagram (`direct_threads`).

Quando arriva un messaggio nuovo:

- JARVIS dice vocalmente:
  *"Signore, nuovo messaggio &lt;piattaforma&gt; da &lt;mittente&gt;"*;
- memorizza il mittente come "ultimo in arrivo" per quella piattaforma
  (in `actions/message_state.py`).

### 3. Risposta vocale automatica
Dopo aver sentito la notifica, basta dire:

> *"Rispondi con ci sentiamo dopo"*
> *"Rispondigli ok"*
> *"Digli arrivo tra 5 minuti"*

JARVIS richiama subito il tool `send_message` con `receiver` e
`platform` precompilati dall'ultimo mittente — la risposta parte
**immediatamente** sulla stessa piattaforma, senza conferme e
senza aprire nulla.

---

## Tutto via TOKEN / SESSION — niente credenziali in chiaro

Nessuna piattaforma richiede username+password ogni volta. Tutte le
integrazioni usano TOKEN o file di sessione autenticati **una sola
volta** e riusati per sempre.

| Piattaforma | Meccanismo | Cosa serve |
|---|---|---|
| Discord    | User-token (header `Authorization`) | `DISCORD_USER_TOKEN` in `.env` |
| Telegram   | MTProto session (Telethon)          | `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` in `.env`, primo login interattivo |
| WhatsApp   | Bridge HTTP locale `whatsapp-web.js` | scansione QR una tantum, poi `WHATSAPP_BRIDGE_URL` |
| Instagram  | Session `instagrapi`                | `~/.jarvis_ig.json` generato la prima volta |

---

## Setup rapido

### 1. Clona e installa
```bash
git clone <questo repo> jarvis_app
cd jarvis_app
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install
```

### 2. Chiavi base (Gemini + OpenRouter)
`config/api_keys.json`:
```json
{
  "gemini_api_key":    "AIza...",
  "openrouter_api_key": "sk-or-..."
}
```

### 3. File `.env` — credenziali della dashboard
Nella **root del progetto** trovi gia' un `.env` di esempio. Aprilo e
inserisci i tuoi valori (lascia vuoti quelli che non usi: la
dashboard segnala la mancanza ma non crasha):

```ini
DISCORD_USER_TOKEN=MTAxxxxxxxxxxxxxxxxx.GZeXXX.YYY
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=abcd1234ef5678...
WHATSAPP_BRIDGE_URL=http://127.0.0.1:8765
```

#### Dove recupero questi valori?

- **`DISCORD_USER_TOKEN`** — apri https://discord.com, F12 → tab
  *Network* → fai click su qualsiasi chat → guarda una richiesta a
  `/api/v9/...` → copia il valore dell'header `Authorization`.
  ⚠️ Self-bot: viola i ToS Discord, usalo a tuo rischio.
- **`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`** — vai su
  https://my.telegram.org → *API development tools* → crea
  un'app e copia ID + Hash. Al PRIMO avvio Telethon ti chiede
  numero + codice di conferma → crea `~/.jarvis_tg.session`.
  Dalle volte successive: zero login.
- **`WHATSAPP_BRIDGE_URL`** — default `http://127.0.0.1:8765`, basta
  avviare il bridge locale (sezione sotto).

### 4. Bridge WhatsApp (una sola volta)
Nel repo trovi gia' la cartella `wa-bridge/` pronta all'uso (server
Node basato su `whatsapp-web.js` v1.34+, npm).

**Requisito:** Node.js >= 18.

```bash
cd wa-bridge
npm install
npm start
```

Al primo avvio nel terminale vedi un **QR code**. Aprilo dal telefono:

> WhatsApp > Impostazioni > Dispositivi collegati > Collega un dispositivo

Scansiona — la sessione viene salvata in `wa-bridge/.wwebjs_auth/` e
funziona come token permanente. Dalle volte successive `npm start`
parte gia' loggato. JARVIS si collega su `WHATSAPP_BRIDGE_URL` letta
dal `.env`.

### 5. Login Instagram (una sola volta)
Nel repo trovi `setup_instagram.py`:

```bash
python setup_instagram.py
```

Lo script chiede username/password (e codice 2FA se attivo), fa il
login con `instagrapi`, salva la sessione in `~/.jarvis_ig.json` e
scarta la password. Da quel momento JARVIS usa solo quel file —
niente piu' username/password.

### 6. Avvio
```bash
python main.py             # versione con UI Tk
# oppure
python main_headless.py    # versione console-only
```

---

## Comandi vocali principali

| Comando | Cosa fa |
|---|---|
| *"Jarvis invia un messaggio"*                                | Apre la dashboard cross-platform |
| *"Jarvis manda un messaggio su Discord a Mario: ciao"*       | Invio diretto via API, senza dashboard |
| *"Jarvis ho messaggi da leggere?"*                           | Riassume i non letti di tutte le piattaforme |
| *"Rispondi con ci sentiamo dopo"*                            | (Dopo notifica) Risponde all'ultimo mittente sulla stessa piattaforma |

---

## Architettura — parti chiave della dashboard

```
jarvis_app/
  .env                          # <-- credenziali (DISCORD_USER_TOKEN, ecc.)
  main.py                       # Loop principale + tool dispatcher Gemini Live
  ui.py                         # UI Tkinter + overlay
  actions/
    send_message.py             # Tool 'send_message': diretto o apri dashboard
    send_dashboard.py           # Dashboard PyQt6 + sender via API/token
                                #   (eseguito come `python -m actions.send_dashboard`)
    check_messages.py           # gather_unread() + start_notification_pollers()
                                #   -> annuncio vocale + set_last_incoming(...)
    message_state.py            # Stato condiviso "ultimo messaggio in arrivo"
    whatsapp_bridge.py          # Wrapper HTTP per il bridge whatsapp-web.js
```

### Caricamento delle credenziali
`send_dashboard.py`, `send_message.py`, `check_messages.py` e
`whatsapp_bridge.py` chiamano `dotenv.load_dotenv(...)` all'import,
puntando al file `.env` nella root del progetto. In questo modo i token
sono disponibili sia nel processo principale di JARVIS sia nel
**subprocess** che ospita la GUI PyQt6 — il fix che mancava nelle
versioni precedenti.

### Perche' la dashboard gira in subprocess?
PyQt6 vuole il proprio main thread. JARVIS gira il loop Gemini Live in
un task asyncio su un thread separato dal `Tk.mainloop()`. Aprire una
`QApplication` da quel worker thread causava:

```
QObject: Cannot create children for a parent that is in a different thread.
```

Soluzione: `subprocess.Popen([python, "-m", "actions.send_dashboard"])`.
Il figlio ha un suo main thread, un suo `QApplication`, e quando
l'utente chiude la finestra il processo esce — senza toccare JARVIS.

---

## Limitazioni note

- **Discord user-token**: viola i ToS Discord. Account a rischio ban.
- **WhatsApp**: richiede il bridge `whatsapp-web.js` attivo localmente.
  Se non raggiungibile, scan/invio WhatsApp tornano errore (la
  dashboard non crasha).
- **Instagram**: l'account potrebbe richiedere 2FA/verifica al primo
  login `instagrapi`.
- **OS**: testato su Windows 10/11. La parte di **messaggistica e'
  OS-agnostic**; le azioni di sistema legacy (pywin32, pycaw, win10toast)
  funzionano solo su Windows.

---

## Licenza

Uso personale e non commerciale. Licenza originale del progetto:
Creative Commons BY-NC 4.0.
