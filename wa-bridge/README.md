# JARVIS - WhatsApp Bridge

Bridge HTTP locale che permette a JARVIS di inviare/ricevere messaggi su
WhatsApp via `whatsapp-web.js`, **senza aprire WhatsApp Web** nella tua
sessione di lavoro.

## Setup (una sola volta)

```bash
cd wa-bridge
npm install
npm start
```

Al primo avvio appare un QR-code nel terminale. Aprilo da telefono:

> WhatsApp > Impostazioni > Dispositivi collegati > Collega un dispositivo

Scansiona. La sessione viene salvata in `.wwebjs_auth/` e funziona come
token permanente: dalle volte successive `npm start` parte gia' loggato.

## Endpoint

- `GET  /status`  -> `{ ready, qr, online, error }`
- `GET  /chats`   -> elenco chat `{ id, name, isGroup }`
- `GET  /unread`  -> coda messaggi in arrivo (svuotata ad ogni chiamata)
- `POST /send`    -> body `{ to|name, text }` invia un messaggio

## Troubleshooting Windows

### Errore `Failed to launch the browser process: Code: 3221226505`

`3221226505` (= `0xC0000409` STATUS_STACK_BUFFER_OVERRUN) significa che
il Chromium "bundled" di puppeteer e' crashato all'avvio. Cause tipiche:

1. **Il path contiene spazi o caratteri non-ASCII**
   (es. `C:\Users\windows\Downloads\EJAAAAA DIO\wa-bridge`).
   **Soluzione**: sposta la cartella in un path semplice come
   `C:\jarvis\wa-bridge` e ri-esegui `npm start`.

2. **Chromium bundled incompatibile** con la tua build di Windows.
   Il bridge ora cerca automaticamente Chrome / Edge nelle posizioni
   standard:
   - `C:\Program Files\Google\Chrome\Application\chrome.exe`
   - `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
   - `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`
   - `C:\Program Files\Microsoft\Edge\Application\msedge.exe`
   - `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

   Se ne trova uno, lo usa al posto del Chromium bundled. Se nessuno
   e' presente, **installa Google Chrome** e riavvia il bridge.

3. **Antivirus** che blocca puppeteer alla prima esecuzione.
   Disattivalo temporaneamente per il primo avvio.

4. **Override manuale**: imposta la variabile d'ambiente
   `CHROME_PATH` puntando al tuo chrome.exe e riavvia:
   ```cmd
   set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
   npm start
   ```

## Note

- Richiede Node.js >= 18.
- La cartella `.wwebjs_auth/` contiene cookie/token: non condividerla.
- Override porta/host: `WA_HOST` / `WA_PORT` (default `127.0.0.1:8765`).
