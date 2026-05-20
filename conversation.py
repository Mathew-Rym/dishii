"""
conversation.py — Persistent Conversation State Manager
Stores conversation states in Supabase (not memory).
Survives restarts, scales to multiple instances.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _db():
    from supabase import create_client
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def get_state(phone: str) -> Optional[Dict]:
    """Get active conversation state for a phone number."""
    try:
        r = _db().table("conversation_state")\
            .select("*")\
            .eq("phone", phone)\
            .execute()
        if not r.data:
            return None
        row = r.data[0]
        # Check expiry
        expires = datetime.fromisoformat(row["expires_at"].replace("Z",""))
        if datetime.utcnow() > expires:
            clear_state(phone)
            return None
        ctx = row.get("context", {})
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        return {
            "state":    row["state"],
            "store_id": row.get("store_id"),
            "context":  ctx
        }
    except Exception as e:
        logger.error(f"get_state: {e}")
        return None


def set_state(phone: str, state: str, store_id: str,
              context: Dict, ttl_minutes: int = 30) -> bool:
    """Set or update conversation state for a phone number."""
    expires = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat()
    try:
        # Upsert — update if exists, insert if not
        existing = _db().table("conversation_state")\
            .select("id").eq("phone", phone).execute()

        if existing.data:
            _db().table("conversation_state").update({
                "state":      state,
                "store_id":   store_id,
                "context":    context,
                "expires_at": expires,
                "created_at": datetime.utcnow().isoformat()
            }).eq("phone", phone).execute()
        else:
            _db().table("conversation_state").insert({
                "phone":      phone,
                "state":      state,
                "store_id":   store_id,
                "context":    context,
                "expires_at": expires
            }).execute()
        return True
    except Exception as e:
        logger.error(f"set_state: {e}")
        return False


def clear_state(phone: str) -> bool:
    """Clear conversation state for a phone number."""
    try:
        _db().table("conversation_state")\
            .delete().eq("phone", phone).execute()
        return True
    except Exception as e:
        logger.error(f"clear_state: {e}")
        return False


def log_decision(procurement_id: str, store_id: str, manager_phone: str,
                 decision: str, original_qty: int = None,
                 revised_qty: int = None, original_supplier: str = None,
                 revised_supplier: str = None, delay_days: int = None,
                 notes: str = None) -> bool:
    """Log every procurement decision for audit trail and ML training."""
    try:
        _db().table("procurement_decisions").insert({
            "procurement_id":    procurement_id,
            "store_id":          store_id,
            "manager_phone":     manager_phone,
            "decision":          decision,
            "original_qty":      original_qty,
            "revised_qty":       revised_qty,
            "original_supplier": original_supplier,
            "revised_supplier":  revised_supplier,
            "delay_days":        delay_days,
            "notes":             notes,
            "decided_at":        datetime.utcnow().isoformat()
        }).execute()
        return True
    except Exception as e:
        logger.error(f"log_decision: {e}")
        return False