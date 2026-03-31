# MailBridge

MailBridge is a FastAPI-based app to translate and send emails.

The app uses:
- Google Sign-In for user authentication
- Google Translate web endpoint for translation
- A separate Gmail MCP server for Gmail API sending

## Architecture

Flow:

1. Frontend calls main API on port 8000
2. Main API translates content and validates session
3. Main API forwards send request to Gmail MCP server on port 8001
4. Gmail MCP server sends email via Gmail API

Components:

- main.py: Main app (auth, session, translation, orchestration)
- gmail_mcp_server.py: Gmail sender service with OAuth token handling
- static/index.html: Frontend UI
- .env: Local environment configuration (do not commit)

## Features

- Login with Google
- Translate email content between languages
- Send translated emails through Gmail API
- One-click Translate and Send flow
- SQLite-backed sessions

## Requirements

- Python 3.10+
- Pip
- Google OAuth credentials for Gmail API access

## Installation

From the project folder containing requirements.txt:

python -m pip install -r requirements.txt

## Environment Setup

Create or update .env in this folder with your values:

GMAIL_ACCESS_TOKEN=
GMAIL_REFRESH_TOKEN=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_CLIENT_ID=

Notes:

- Recommended mode is refresh-token mode by setting:
	- GMAIL_REFRESH_TOKEN
	- GOOGLE_OAUTH_CLIENT_ID
	- GOOGLE_OAUTH_CLIENT_SECRET
- Access-token-only mode also works but expires frequently.
- GOOGLE_CLIENT_ID is used by frontend Google Sign-In.

## Run Locally

Start Gmail MCP server (terminal 1):

python gmail_mcp_server.py

Start main app (terminal 2):

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

Open in browser:

http://127.0.0.1:8000

## Health Checks

Main app:

http://127.0.0.1:8000/health

MCP server:

http://127.0.0.1:8001/health

MCP health response includes:
- gmail_configured
- auth_mode (refresh_token or access_token)

## API Endpoints

Main API:

- GET /
- GET /health
- POST /translate
- POST /send-email
- POST /translate-and-send
- POST /auth/google
- GET /auth/me
- POST /auth/logout

MCP API:

- GET /health
- POST /send-email

## Security Notes

- Never commit real secrets in .env.
- Rotate tokens and client secrets if exposed.
- Keep .env ignored by git.

## Common Issues

1. Error loading ASGI app

Cause: Running uvicorn from wrong directory.
Fix: Run command from the folder containing main.py.

2. Gmail MCP Server is not running

Cause: MCP service is not started.
Fix: Start python gmail_mcp_server.py first.

3. Invalid authentication credentials from Gmail API

Cause: Expired access token or wrong OAuth config.
Fix: Use refresh-token mode and verify client ID/secret.

## License

Use and modify as needed for your project.

