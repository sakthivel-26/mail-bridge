# MailBridge

Translate and send emails from one app.

## Quick Start

1. Install dependencies

```bash
pip install -r requirements.txt
```

2. Create .env from .env.example and set Gmail values

```env
GMAIL_ADDRESS=your_email@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
```

3. Run from project root

```bash
uvicorn mailbridge.main:app --reload
```

4. Open

http://127.0.0.1:8000

## Use By Everyone (Network/Public)

### Option A: Same Wi-Fi / LAN

Run server on all interfaces:

```bash
uvicorn mailbridge.main:app --host 0.0.0.0 --port 8000
```

Then share:

http://YOUR_LOCAL_IP:8000

### Option B: Public Internet

Deploy to a host like Render, Railway, Fly.io, or any VPS.

Start command:

```bash
uvicorn mailbridge.main:app --host 0.0.0.0 --port $PORT
```

Required environment variables on host:

- GMAIL_ADDRESS
- GMAIL_APP_PASSWORD

## API Endpoints

- GET /
- GET /health
- POST /translate
- POST /send-email
- POST /translate-and-send
- GET /email-templates
- POST /generate-email

## Notes

- Translation provider: Google Translate web endpoint.
- Gmail requires App Password (normal Gmail password will fail).
- Users must connect their own Gmail inside the app before sending.
- Login session is temporary (in-memory) and expires automatically.

