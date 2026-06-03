"""
sheets_connector.py — Google Sheets auto-sync

Removes the manual CSV upload by reading a store's live Google Sheet
directly. Once a store owner shares their sheet (one-time setup), the
agent auto-syncs on every run with zero human action.

Setup (one-time per store):
  1. Create Google Cloud service account, download the JSON key.
  2. Base64-encode it:  base64 -w0 service-account.json
  3. Set GOOGLE_CREDENTIALS env var to that base64 string (Railway / .env).
  4. Share the store's Google Sheet with the service account email.
  5. Store the sheet URL via save_store_sheet(store_id, url).
"""

import os, json, base64, hashlib, logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Auth ─────────────────────────────────────────────────────────

def _get_client():
    """Build an authorised gspread client from the GOOGLE_CREDENTIALS env var."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_b64 = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if not creds_b64:
        logger.debug("GOOGLE_CREDENTIALS not set — Google Sheets sync disabled")
        return None
    try:
        creds_json = json.loads(base64.b64decode(creds_b64).decode("utf-8"))
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Google Sheets auth failed: {e}")
        return None


# ── Sheet operations ──────────────────────────────────────────────

def pull_sheet(sheet_url: str, worksheet_index: int = 0) -> pd.DataFrame | None:
    """
    Pull a Google Sheet and return as a DataFrame.
    Returns None on any failure (connectivity, auth, bad URL).
    """
    gc = _get_client()
    if not gc:
        return None
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(worksheet_index)
        records = ws.get_all_records(numericise_ignore=["all"])
        if not records:
            logger.warning(f"Sheet is empty: {sheet_url[:60]}")
            return None
        df = pd.DataFrame(records)
        # Drop completely empty rows
        df = df.dropna(how="all").reset_index(drop=True)
        logger.info(f"Pulled {len(df)} rows from Google Sheet")
        return df
    except Exception as e:
        logger.error(f"pull_sheet failed for {sheet_url[:60]}: {e}")
        return None


def sheet_hash(df: pd.DataFrame) -> str:
    """Stable hash of a DataFrame so we skip re-processing unchanged sheets."""
    return hashlib.md5(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()


# ── Integration store (uses `integrations` DB table) ─────────────

def get_store_sheet(store_id: str) -> str | None:
    """Return the connected Google Sheet URL for a store, or None."""
    import db
    try:
        r = (
            db.get_db()
            .table("integrations")
            .select("config")
            .eq("store_id", store_id)
            .eq("type", "google_sheets")
            .eq("is_active", True)
            .execute()
        )
        if r.data:
            return r.data[0]["config"].get("sheet_url")
    except Exception as e:
        logger.error(f"get_store_sheet: {e}")
    return None


def save_store_sheet(store_id: str, sheet_url: str) -> bool:
    """Persist a Google Sheet URL for a store (upsert)."""
    import db
    try:
        db.get_db().table("integrations").upsert(
            {
                "store_id": store_id,
                "type": "google_sheets",
                "config": {"sheet_url": sheet_url},
                "is_active": True,
                "connected_at": datetime.now().isoformat(),
            },
            on_conflict="store_id,type",
        ).execute()
        logger.info(f"Saved sheet URL for store {store_id}")
        return True
    except Exception as e:
        logger.error(f"save_store_sheet: {e}")
        return False


def mark_synced(store_id: str, status: str = "ok") -> None:
    """Update last_synced_at and sync_status after a run."""
    import db
    try:
        db.get_db().table("integrations").update(
            {
                "last_synced_at": datetime.now().isoformat(),
                "sync_status": status,
            }
        ).eq("store_id", store_id).eq("type", "google_sheets").execute()
    except Exception as e:
        logger.error(f"mark_synced: {e}")


# ── Main entry used by agent.py ───────────────────────────────────

def auto_sync_store(store_id: str, store_name: str) -> pd.DataFrame | None:
    """
    Pull the latest sheet data for a store.
    Returns a DataFrame ready to pass to ai.process_upload(), or None
    if no sheet is connected or the pull fails.
    """
    sheet_url = get_store_sheet(store_id)
    if not sheet_url:
        return None

    logger.info(f"{store_name}: pulling Google Sheet…")
    df = pull_sheet(sheet_url)
    if df is None or df.empty:
        mark_synced(store_id, "empty")
        return None

    mark_synced(store_id, "ok")
    return df


def disconnect_store_sheet(store_id: str) -> bool:
    """Remove a store's Google Sheet connection."""
    import db
    try:
        db.get_db().table("integrations").update(
            {"is_active": False}
        ).eq("store_id", store_id).eq("type", "google_sheets").execute()
        logger.info(f"Disconnected sheet for store {store_id}")
        return True
    except Exception as e:
        logger.error(f"disconnect_store_sheet: {e}")
        return False


def get_service_account_email() -> str | None:
    """Extract the service account email from GOOGLE_CREDENTIALS for display."""
    creds_b64 = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if not creds_b64:
        return None
    try:
        creds_json = __import__("json").loads(
            __import__("base64").b64decode(creds_b64).decode("utf-8")
        )
        return creds_json.get("client_email")
    except Exception:
        return None