"""Gmail MCP Server (Multi-user version)"""

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
    access_token: str   # 🔥 user-specific token


app = FastAPI(
    title="Gmail MCP Server (Multi-user)",
    version="2.0.0"
)


# ✅ SEND EMAIL
@app.post("/send-email")
async def send_email(req: SendEmailRequest) -> JSONResponse:
    try:
        # ✅ CORRECT PLACE
        access_token = req.access_token

        if not access_token:
            raise HTTPException(status_code=400, detail="Missing access_token")

        if not req.to or not req.subject or not req.body:
            raise HTTPException(status_code=400, detail="Missing email fields")

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

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                GMAIL_SEND_URL,
                json=payload,
                headers=headers
            )

        if response.status_code == 200:
            data = response.json()
            return JSONResponse({
                "success": True,
                "message": f"Email sent to {req.to}",
                "message_id": data.get("id")
            })

        # Gmail error
        try:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", response.text)
        except Exception:
            error_msg = response.text

        raise HTTPException(
            status_code=500,
            detail=f"Gmail API error: {error_msg}"
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