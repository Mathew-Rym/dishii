"""
webhook_server.py — Lightweight Dishii Webhook Receiver
Minimal dependencies to stay within Render free tier memory limits.
"""
import os
import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dishii Webhook", docs_url=None, redoc_url=None)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"service": "dishii-webhook", "status": "running"}

@app.post("/webhook")
async def receive_whatsapp(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"status": "error"}, status_code=400)

    event = payload.get("event", "")
    data  = payload.get("data", {})

    if event != "messages.upsert":
        return JSONResponse(content={"action": "ignored"})

    msg_text   = (data.get("message", {}).get("conversation") or
                  data.get("message", {}).get("extendedTextMessage", {}).get("text", ""))
    from_jid   = data.get("key", {}).get("remoteJid", "")
    is_from_me = data.get("key", {}).get("fromMe", True)

    if is_from_me or not msg_text:
        return JSONResponse(content={"action": "skipped"})

    from_phone = from_jid.replace("@s.whatsapp.net", "").replace("@c.us", "")
    logger.info(f"Incoming from {from_phone}: {msg_text[:50]}")

    try:
        from whatsapp_agent import handle_incoming_message
        import whatsapp as wa
        reply = handle_incoming_message(from_phone, msg_text)
        if reply:
            wa.send_reply(from_phone, reply)
            logger.info(f"Replied to {from_phone}")
            return JSONResponse(content={"action": "replied"})
    except Exception as e:
        logger.error(f"Error: {e}")

    return JSONResponse(content={"action": "no_reply"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8502))
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=port, reload=False)
