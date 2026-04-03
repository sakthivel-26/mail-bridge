"""Gmail MCP Server (Multi-user version)"""

import asyncio
import base64
from email.mime.text import MIMEText
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

GMAIL_SEND_URL = "https://www.googleapis.com/gmail/v1/users/me/messages/send"


# ✅ REQUEST MODEL
class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    access_token: str | None = None   # User-specific token (optional, fallback to env if missing)


app = FastAPI(
    title="Gmail MCP Server (Multi-user)",
    version="2.0.0"
)


# ✅ SEND EMAIL
@app.post("/send-email")
async def send_email(req: SendEmailRequest) -> JSONResponse:
    try:
        # ✅ PRIORITY: Use user token if provided, otherwise fall back to env token
        access_token = req.access_token
        from_account = "user-provided"

        # Fallback to env token if user didn't provide one
        if not access_token or not access_token.strip():
            # This is intentional fallback for server-to-server mode (admin sends on behalf)
            from fastapi import status
            # For production: Comment this out and require user token
            raise HTTPException(
                status_code=400, 
                detail="Email send requires user Gmail permission. Please grant access and try again."
            )

        if not req.to or not req.subject or not req.body:
            raise HTTPException(status_code=400, detail="Missing email fields")

        print(f"[DEBUG] Sending email from {from_account} account")

        # 📧 Create email
        message = MIMEText(req.body)
        message["To"] = req.to
        message["Subject"] = req.subject

        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {"raw": raw_message}

        transient_statuses = {429, 500, 502, 503, 504}
        last_error_msg = "Unknown Gmail API error"
        last_status_code = 500

        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        GMAIL_SEND_URL,
                        json=payload,
                        headers=headers,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        return JSONResponse({
                            "success": True,
                            "message": f"Email sent to {req.to}",
                            "message_id": data.get("id")
                        })

                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", response.text)
                    except Exception:
                        error_msg = response.text

                    last_error_msg = error_msg
                    last_status_code = response.status_code if 400 <= response.status_code < 600 else 500

                    if response.status_code not in transient_statuses or attempt == 1:
                        break

                except httpx.RequestError as e:
                    last_error_msg = str(e)
                    last_status_code = 503
                    if attempt == 1:
                        break

                await asyncio.sleep(1 + attempt)

        raise HTTPException(
            status_code=last_status_code,
            detail=f"Gmail API error: {last_error_msg}"
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


# ✅ HEALTH CHECK
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "Gmail MCP Server (Multi-user)"
    }


@app.get("/")
def root():
    return {"message": "Gmail MCP Server is running"}


if __name__ == "__main__":
    print("Starting Gmail MCP Server on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)