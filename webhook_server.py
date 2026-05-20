"""
webhook_server.py — Dishii WhatsApp Webhook Receiver
Receives incoming messages from Evolution API and routes them to the agent.

Deploy this on Railway/Render alongside your app.
Evolution API must be configured to POST to this URL.

Setup:
  pip install fastapi uvicorn
  python webhook_server.py

Configure Evolution API webhook:
  POST /webhook/set/dishii
  {"url": "https://your-webhook-url.railway.app/webhook", "events": ["MESSAGES_UPSERT"], "enabled": true}
"""
import os
import logging
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dishii Webhook", docs_url=None, redoc_url=None)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET","dishii_webhook_2026")


@app.get("/health")
async def health():
    return {"status":"ok","service":"dishii-webhook"}


@app.post("/webhook")
async def receive_whatsapp(request: Request):
    """Main webhook endpoint — receives all Evolution API events."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    logger.info(f"Webhook received: event={payload.get('event','?')}")
    
    try:
        from whatsapp_agent import process_webhook
        result = process_webhook(payload)
        logger.info(f"Webhook result: {result}")
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return JSONResponse(content={"status":"error","message":str(e)}, status_code=500)


@app.post("/webhook/configure")
async def configure_webhook(request: Request):
    """
    Helper endpoint to register this webhook with Evolution API.
    POST to this endpoint with {"webhook_url": "https://..."}
    """
    try:
        body  = await request.json()
        token = body.get("secret","")
        if token != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret")
        
        webhook_url = body.get("webhook_url","")
        if not webhook_url:
            raise HTTPException(status_code=400, detail="webhook_url required")
        
        import requests
        evolution_url = os.getenv("EVOLUTION_URL","").rstrip("/")
        evolution_key = os.getenv("EVOLUTION_KEY","")
        instance      = os.getenv("EVOLUTION_INSTANCE","dishii")
        
        r = requests.post(
            f"{evolution_url}/webhook/set/{instance}",
            headers={"Content-Type":"application/json","apikey":evolution_key},
            json={
                "url":    webhook_url + "/webhook",
                "events": ["MESSAGES_UPSERT"],
                "enabled":True
            },
            timeout=15
        )
        return JSONResponse(content={"configured":r.status_code in (200,201),"response":r.json()})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(content={"error":str(e)}, status_code=500)


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_PORT","8502"))
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=port, reload=False)