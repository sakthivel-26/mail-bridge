"""Gmail MCP Server: sends Gmail via HTTP endpoint for the main app."""

import base64
import os
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://www.googleapis.com/gmail/v1/users/me/messages/send"


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str


class GmailAuth:
    """Resolves a valid access token from either access token or refresh token flow."""

    def __init__(self) -> None:
        self.access_token = os.getenv("GMAIL_ACCESS_TOKEN", "").strip()
        self.refresh_token = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
        self.client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        self._access_token_expires_at = 0.0

        # Backward-compatible guard: refresh tokens often start with "1//".
        # If user pasted refresh token into GMAIL_ACCESS_TOKEN, recover automatically.
        if self.access_token.startswith("1//") and not self.refresh_token:
            self.refresh_token = self.access_token
            self.access_token = ""

    async def get_access_token(self) -> str:
        # If direct access token is configured, use it.
        if self.access_token and not self.refresh_token:
            return self.access_token

        # If we have a cached refreshed token and it is still valid, reuse it.
        if self.access_token and time.time() < self._access_token_expires_at:
            return self.access_token

        # Otherwise refresh token flow is required.
        if not (self.refresh_token and self.client_id and self.client_secret):
            raise HTTPException(
                status_code=500,
                detail=(
                    "OAuth config missing. Set either GMAIL_ACCESS_TOKEN or all of: "
                    "GMAIL_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET"
                ),
            )

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=payload)

        if response.status_code != 200:
            error_detail = response.text
            raise HTTPException(
                status_code=500,
                detail=f"Failed to refresh Gmail access token: {error_detail}",
            )

        data = response.json()
        token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 3600))
        if not token:
            raise HTTPException(status_code=500, detail="Token refresh response missing access_token")

        self.access_token = token
        self._access_token_expires_at = time.time() + max(60, expires_in - 60)
        return self.access_token


class SendEmailTool:
    """Tool to send emails via Gmail API."""

    def __init__(self, auth: GmailAuth):
        self.auth = auth

    async def send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        access_token = await self.auth.get_access_token()

        # Create RFC2822 message and Base64URL encode for Gmail API.
        message = MIMEText(body)
        message["To"] = to
        message["Subject"] = subject
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"raw": raw_message}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(GMAIL_SEND_URL, json=payload, headers=headers)

        if response.status_code == 200:
            body_json = response.json()
            return {
                "success": True,
                "message": f"Email sent to {to}",
                "message_id": body_json.get("id"),
            }

        error_msg = response.json().get("error", {}).get("message", response.text)
        return {"success": False, "error": f"Gmail API error: {error_msg}"}


app = FastAPI(title="Gmail MCP Server", version="1.1.0")
auth = GmailAuth()
tool = SendEmailTool(auth)


@app.post("/send-email")
async def send_email_endpoint(req: SendEmailRequest) -> JSONResponse:
    result = await tool.send_email(req.to, req.subject, req.body)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Email send failed"))
    return JSONResponse(result)


@app.get("/health")
def health() -> dict[str, Any]:
    using_refresh_flow = bool(auth.refresh_token and auth.client_id and auth.client_secret)
    return {
        "status": "ok",
        "service": "Gmail MCP Server",
        "gmail_configured": bool(auth.access_token or auth.refresh_token),
        "auth_mode": "refresh_token" if using_refresh_flow else "access_token",
    }


if __name__ == "__main__":
    print("Starting Gmail MCP Server on port 8001...")
    uvicorn.run(app, host="127.0.0.1", port=8001)
