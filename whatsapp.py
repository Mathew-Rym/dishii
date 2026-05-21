"""
whatsapp.py v10 — Dishii WhatsApp Engine
Complete rewrite:
- Phone normalization (any country format)
- Message deduplication (no more duplicates)
- Batch procurement messages
- New enterprise briefing format
- Reorder validation (expired items never reorder)
"""
import os
import re
import hashlib
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

EVOLUTION_URL      = os.getenv("EVOLUTION_URL", "").rstrip("/")
EVOLUTION_KEY      = os.getenv("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "dishii")

def _headers():
    return {"Content-Type": "application/json", "apikey": EVOLUTION_KEY}

_DIV = "━━━━━━━━━━━━━━━━━━━━"


# ════════════════════════════════════════════════════════════════
# PHONE NORMALIZATION
# ════════════════════════════════════════════════════════════════

def normalize_phone(phone: str, default_country: str = "254") -> str:
    """
    Accepts any phone format, returns clean E.164 digits (no + sign).
    0720521291       → 254720521291
    +254 720 521 291 → 254720521291
    720521291        → 254720521291
    +44 7911 123456  → 447911123456
    +1 212 555 1234  → 12125551234
    """
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone))
    if not digits:
        return ""

    # Already has country code (starts with known prefix, correct length)
    known = {
        "254":9,"255":9,"256":9,"250":9,"251":9,"252":9,
        "234":10,"233":9,"27":9,"263":9,"260":9,
        "1":10,"44":10,"91":10,"971":9,"966":9,"49":10,
        "33":9,"39":10,"34":9,"61":9,"64":9,"81":10,
    }
    for prefix in sorted(known.keys(), key=len, reverse=True):
        if digits.startswith(prefix):
            expected = len(prefix) + known[prefix]
            if len(digits) >= expected:
                return digits[:expected]
            break

    # Local 0XXXXXXXXX format
    if digits.startswith("0") and len(digits) >= 9:
        return default_country + digits[1:]

    # 9-digit starting with 7 (Kenya local without 0)
    if len(digits) == 9 and digits.startswith("7"):
        return default_country + digits

    return digits

def display_phone(phone: str) -> str:
    """Returns +254720521291 format for display."""
    n = normalize_phone(phone)
    return f"+{n}" if n else phone


# ════════════════════════════════════════════════════════════════
# CONNECTION
# ════════════════════════════════════════════════════════════════

def get_connection_status() -> str:
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        return "not_configured"
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/instance/connectionState/{EVOLUTION_INSTANCE}",
            headers=_headers(), timeout=5
        )
        if r.status_code == 200:
            return r.json().get("instance", {}).get("state", "unknown")
    except Exception:
        pass
    return "disconnected"

def is_connected() -> bool:
    return get_connection_status() == "open"


# ════════════════════════════════════════════════════════════════
# DEDUPLICATION — prevents duplicate messages
# ════════════════════════════════════════════════════════════════

_dedup_cache: Dict[str, datetime] = {}

DEDUP_WINDOWS = {
    "alert":         timedelta(minutes=5),
    "procurement":   timedelta(minutes=10),
    "briefing":      timedelta(hours=1),
    "upload_alert":  timedelta(minutes=15),
    "supplier_order":timedelta(hours=1),
    "default":       timedelta(minutes=5),
}

def _dedup_key(phone: str, msg_type: str, content: str) -> str:
    raw = f"{phone}|{msg_type}|{content[:120]}"
    return hashlib.md5(raw.encode()).hexdigest()

def _is_duplicate(phone: str, msg_type: str, content: str) -> bool:
    key    = _dedup_key(phone, msg_type, content)
    window = DEDUP_WINDOWS.get(msg_type, DEDUP_WINDOWS["default"])
    last   = _dedup_cache.get(key)
    if last and (datetime.now() - last) < window:
        logger.info(f"Dedup skip [{msg_type}] to {phone[:6]}...")
        return True
    _dedup_cache[key] = datetime.now()
    # Cleanup stale entries
    cutoff = datetime.now() - timedelta(hours=2)
    stale  = [k for k, v in _dedup_cache.items() if v < cutoff]
    for k in stale:
        del _dedup_cache[k]
    return False


# ════════════════════════════════════════════════════════════════
# SEND
# ════════════════════════════════════════════════════════════════

def send(phone: str, text: str, msg_type: str = "default",
         skip_dedup: bool = False) -> bool:
    """Send WhatsApp. Normalizes phone, deduplicates, sends."""
    clean = normalize_phone(phone)
    if not clean:
        logger.warning(f"send(): invalid phone '{phone}'")
        return False
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        logger.warning("send(): Evolution API not configured")
        return False
    if not skip_dedup and _is_duplicate(clean, msg_type, text):
        return False
    try:
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}",
            headers=_headers(),
            json={"number": clean, "text": text},
            timeout=15
        )
        ok = r.status_code in (200, 201)
        if not ok:
            logger.error(f"send() {r.status_code}: {r.text[:150]}")
        return ok
    except requests.Timeout:
        logger.error(f"send() timeout: {clean}")
        return False
    except Exception as e:
        logger.error(f"send() error: {e}")
        return False

def send_to_all(phones: List[str], text: str,
                msg_type: str = "default") -> int:
    return sum(1 for p in phones if send(p, text, msg_type))

def send_reply(phone: str, text: str) -> bool:
    """Direct reply — always sends, no dedup."""
    return send(phone, text, "query_response", skip_dedup=True)


# ════════════════════════════════════════════════════════════════
# REORDER VALIDATION
# ════════════════════════════════════════════════════════════════

def should_reorder(item: dict) -> bool:
    """
    Returns True ONLY for genuine stockout risk.
    NEVER reorders: expired, waste, or overstocked items.
    """
    if item.get("is_expired", False):
        return False
    if item.get("risk_type", "") in ("WASTE", "OVERSTOCK"):
        return False
    return (
        item.get("order_required", False) and
        item.get("risk_type", "") == "STOCKOUT"
    )


# ════════════════════════════════════════════════════════════════
# MESSAGE TEMPLATES — Enterprise format
# ════════════════════════════════════════════════════════════════

def msg_operational_briefing(store_name: str, summary: dict,
                              expired_items: list, reorder_items: list,
                              procurement_queue: list, watch_items: list,
                              briefing_text: str = "") -> str:
    """Main operational briefing — Palantir-style, enterprise format."""
    now   = datetime.now().strftime("%d %b %Y, %H:%M")
    tv    = float(summary.get("total_value", 0) or 0)
    waste = float(summary.get("waste_value", 0) or 0)
    crit  = summary.get("critical", 0)
    high  = summary.get("high", 0)
    low   = summary.get("low", 0)
    hs    = summary.get("health_score", 0)

    # Section: Immediate actions
    remove_lines = [
        f"• {i['product_name']} ({int(i.get('current_stock',0))} units)"
        for i in expired_items[:5]
    ]
    reorder_lines = [
        f"• {i['product_name']} — {int(i.get('current_stock',0))} left ({int(i.get('stock_days',0))}d)"
        for i in reorder_items[:5]
    ]

    immediate = ""
    if remove_lines:
        immediate += "❌ *REMOVE FROM SHELF*\n" + "\n".join(remove_lines)
    if remove_lines and reorder_lines:
        immediate += "\n\n"
    if reorder_lines:
        immediate += "🔄 *REORDER NOW*\n" + "\n".join(reorder_lines)
    if not immediate:
        immediate = "✅ No immediate actions required"

    # Section: Procurement queue
    proc_lines = []
    total_proc  = 0
    for idx, item in enumerate(procurement_queue[:5], 1):
        rate  = float(item.get("daily_sales_rate", 1) or 1)
        qty   = max(1, int(rate * 14))
        price = float(item.get("selling_price", 0) or 0)
        val   = qty * price
        total_proc += val
        proc_lines.append(
            f"{idx}. *{item['product_name']}* — {qty} units\n"
            f"   {item.get('supplier','Unknown')} | KES {val:,.0f}"
        )

    proc_section = "\n\n".join(proc_lines) if proc_lines else "No orders pending"
    proc_reply   = (
        "\n\nReply:\n"
        "*APPROVE ALL*\n"
        "*REJECT ALL*\n"
        "*APPROVE 1,2* (specific)\n"
        f"*REJECT 3*\n\n"
        f"Total: *KES {total_proc:,.0f}*"
    ) if proc_lines else ""

    # Section: Watch today
    watch_lines = [
        f"• {i['product_name']} — {i.get('risk_reason','')}"
        for i in watch_items[:3]
    ]
    watch_section = "\n".join(watch_lines) if watch_lines else "• All categories within range"

    # AI insight
    ai_section = f"\n{_DIV}\n🤖 *AI INSIGHT*\n{briefing_text}" if briefing_text else ""

    return (
        f"📊 *DISHII OPERATIONAL BRIEFING*\n"
        f"*{store_name}*  ·  {now}\n\n"
        f"{_DIV}\n"
        f"🚨 *IMMEDIATE ACTIONS*\n\n"
        f"{immediate}\n\n"
        f"{_DIV}\n"
        f"💰 *FINANCIAL RISK*\n\n"
        f"⚠️ Waste at Risk: *KES {waste:,.0f}*\n"
        f"📉 Revenue Impact: *KES {waste*1.6:,.0f}*\n"
        f"_{crit} critical SKUs need action_\n\n"
        f"{_DIV}\n"
        f"🛒 *PROCUREMENT QUEUE*\n\n"
        f"{proc_section}"
        f"{proc_reply}\n\n"
        f"{_DIV}\n"
        f"📦 *STORE HEALTH*\n\n"
        f"🔴 Critical: {crit}  🟠 High: {high}  🟢 Healthy: {low}\n"
        f"Value: *KES {tv:,.0f}*  ·  Health: *{hs}%*\n\n"
        f"{_DIV}\n"
        f"📅 *WATCH TODAY*\n\n"
        f"{watch_section}"
        f"{ai_section}\n\n"
        f"{_DIV}\n"
        f"_Powered by Dishii AI_"
    )

def msg_batch_procurement(store_name: str, items: list) -> str:
    """Batched procurement approval — one message for all pending orders."""
    if not items:
        return ""
    lines = []
    total = 0
    for idx, item in enumerate(items, 1):
        # Use actual values from DB procurement request
        qty   = int(item.get("suggested_qty") or item.get("daily_sales_rate", 1) or 1)
        if qty < 2: qty = max(1, int(float(item.get("daily_sales_rate",1) or 1) * 14))
        val   = float(item.get("total_value") or 0)
        if val == 0:
            price = float(item.get("unit_price") or item.get("selling_price", 0) or 0)
            val   = qty * price
        total += val
        urg   = "🔴" if item.get("severity_level") == "CRITICAL" else "🟠"
        lines.append(
            f"{idx}. {urg} *{item['product_name']}*\n"
            f"   {qty} units · KES {val:,.0f}\n"
            f"   Supplier: {item.get('supplier','Unknown')}"
        )
    return (
        f"🛒 *PROCUREMENT QUEUE — {store_name}*\n"
        f"_{datetime.now().strftime('%d %b, %H:%M')}_\n\n"
        f"{_DIV}\n\n"
        + "\n\n".join(lines) +
        f"\n\n{_DIV}\n"
        f"*Total: KES {total:,.0f}*\n\n"
        f"Reply:\n"
        f"*APPROVE ALL*\n"
        f"*REJECT ALL*\n"
        f"*APPROVE 1,3* — approve specific\n"
        f"*REJECT 2* — reject specific"
    )

def msg_rejection_followup(product: str, ref_id: str,
                            current_qty: int = 0,
                            supplier: str = "") -> str:
    return (
        f"Order rejected — *{product}*\n\n"
        f"Current: {current_qty} units · {supplier}\n\n"
        f"What would you like to do?\n\n"
        f"1️⃣ Reduce quantity\n"
        f"2️⃣ Change supplier\n"
        f"3️⃣ Delay order\n"
        f"4️⃣ Cancel completely\n\n"
        f"Reply with:\n"
        f"*1 [qty]* — e.g. `1 50`\n"
        f"*2 [supplier]* — e.g. `2 Brookside`\n"
        f"*3 [days]* — e.g. `3 3`\n"
        f"*4* — cancel\n\n"
        f"_Ref: {str(ref_id)[:8].upper()}_"
    )

def msg_update_confirm(product: str, change_desc: str,
                        original: str, updated: str,
                        estimated_value: float, ref_id: str) -> str:
    return (
        f"✏️ *Procurement Update*\n\n"
        f"Product: *{product}*\n"
        f"Change: {change_desc}\n"
        f"Before: {original}\n"
        f"After: *{updated}*\n"
        f"Value: KES {estimated_value:,.0f}\n\n"
        f"Reply *YES* to confirm\n"
        f"Reply *NO* to cancel\n\n"
        f"_Ref: {str(ref_id)[:8].upper()}_"
    )

def msg_update_confirmed(product: str, action: str) -> str:
    return f"✅ *{product}* — {action}\n_Supplier will be notified._"

def msg_update_cancelled(product: str) -> str:
    return (
        f"Order unchanged — *{product}*\n\n"
        f"What would you like?\n"
        f"1. Try different quantity\n"
        f"2. Cancel order\n"
        f"3. Keep original\n\n"
        f"Reply: 1 / 2 / 3"
    )

def msg_procurement_request(store_name: str, product: str, qty: int,
                              supplier: str, value: float,
                              request_id: str, urgency: str) -> str:
    emoji = "🔴" if urgency == "CRITICAL" else "🟠"
    return (
        f"{emoji} *Procurement — {store_name}*\n\n"
        f"Product: *{product}*\n"
        f"Supplier: {supplier}\n"
        f"Quantity: *{qty} units*\n"
        f"Value: KES {value:,.0f}\n\n"
        f"Reply:\n"
        f"*YES {str(request_id)[:8].upper()}* to approve\n"
        f"*NO {str(request_id)[:8].upper()}* to adjust\n\n"
        f"_Ref: {str(request_id)[:8].upper()}_"
    )

def msg_procurement_approved(product: str, qty: int, supplier: str,
                               value: float, request_id: str) -> str:
    return (
        f"✅ *Order Approved*\n\n"
        f"*{product}*\n"
        f"Qty: {qty} units · KES {value:,.0f}\n"
        f"Supplier: {supplier}\n"
        f"Ref: {str(request_id)[:8].upper()}\n\n"
        f"_Supplier notified._"
    )

def msg_procurement_rejected(product: str, request_id: str) -> str:
    return (
        f"❌ *Rejected — {product}*\n"
        f"Ref: {str(request_id)[:8].upper()}"
    )

def msg_stock_alert(store_name: str, product: str, risk: str,
                     stock: int, stock_days: int, reason: str) -> str:
    emoji = {"CRITICAL":"🔴","HIGH":"🟠","MEDIUM":"🟡"}.get(risk,"🟡")
    return (
        f"{emoji} *Alert — {store_name}*\n\n"
        f"*{product}*\n"
        f"{reason}\n"
        f"Stock: {stock} units · {stock_days}d left"
    )

def msg_supplier_order(store_name: str, product: str,
                        qty: int, request_id: str) -> str:
    return (
        f"📦 *New Order — {store_name}*\n\n"
        f"Product: *{product}*\n"
        f"Quantity: *{qty} units*\n"
        f"Ref: {str(request_id)[:8].upper()}\n\n"
        f"Confirm availability and delivery date.\n"
        f"Reply: *CONFIRMED {str(request_id)[:8].upper()}*"
    )

def msg_hourly_briefing(store_name: str, briefing_text: str, summary: dict) -> str:
    """Backward-compatible — uses new format internally."""
    return (
        f"📊 *Dishii — {store_name}*\n"
        f"_{datetime.now().strftime('%d %b %Y, %H:%M')}_\n\n"
        f"{briefing_text}\n\n"
        f"{_DIV}\n"
        f"🔴 {summary.get('critical',0)}  "
        f"🟠 {summary.get('high',0)}  "
        f"🟢 {summary.get('low',0)}  "
        f"💰 KES {float(summary.get('total_value',0)):,.0f}"
    )

def msg_welcome(store_name: str, manager_name: str) -> str:
    return (
        f"👋 Welcome, *{manager_name}*!\n\n"
        f"You are managing *{store_name}* on Dishii.\n\n"
        f"You will receive:\n"
        f"🔴 Critical alerts\n"
        f"📊 AI briefings\n"
        f"📦 Procurement approvals\n\n"
        f"Commands:\n"
        f"• _critical items_\n"
        f"• _orders needed_\n"
        f"• _briefing_\n"
        f"• _help_\n\n"
        f"_Dishii AI — Autonomous Food Operations_"
    )


# ════════════════════════════════════════════════════════════════
# REPLY PARSER
# ════════════════════════════════════════════════════════════════

def parse_manager_reply(text: str) -> dict:
    """
    Parse any manager reply into a structured action dict.
    Handles:
      APPROVE ALL / REJECT ALL
      APPROVE 1,3 / REJECT 2
      YES ref / NO ref
      1 100 / 2 Supplier / 3 3 / 4   (rejection follow-up)
      YES / NO                        (confirmation)
    """
    clean = text.strip()
    upper = clean.upper()
    parts = clean.split()

    YES_W = {"YES","Y","APPROVE","OK","SAWA","NDIO","CONFIRMED"}
    NO_W  = {"NO","N","REJECT","SKIP","HAPANA"}

    # Batch commands
    if upper in ("APPROVE ALL", "YES ALL"):
        return {"action": "APPROVE_ALL"}
    if upper in ("REJECT ALL", "NO ALL"):
        return {"action": "REJECT_ALL"}

    m = re.match(r"^APPROVE\s+([\d,\s]+)$", upper)
    if m:
        nums = [int(n.strip()) for n in m.group(1).split(",") if n.strip().isdigit()]
        return {"action": "APPROVE_SELECTIVE", "indices": nums}

    m = re.match(r"^REJECT\s+([\d,\s]+)$", upper)
    if m:
        nums = [int(n.strip()) for n in m.group(1).split(",") if n.strip().isdigit()]
        return {"action": "REJECT_SELECTIVE", "indices": nums}

    # Single YES/NO with optional ref
    if parts and parts[0].upper() in YES_W:
        return {"action": "YES", "ref_id": parts[1] if len(parts) > 1 else None}
    if parts and parts[0].upper() in NO_W:
        return {"action": "NO", "ref_id": parts[1] if len(parts) > 1 else None}

    # Rejection follow-up: 1 100 / 2 Brookside / 3 3 / 4
    if parts and parts[0] in ("1", "2", "3", "4"):
        option = int(parts[0])
        detail = " ".join(parts[1:]) if len(parts) > 1 else ""
        sub    = {1:"REDUCE_QTY", 2:"CHANGE_SUPPLIER",
                   3:"DELAY_ORDER", 4:"CANCEL"}[option]
        return {"action": "REJECTION_FOLLOWUP",
                "option": option, "sub_action": sub, "detail": detail}

    return {"action": "UNKNOWN", "raw": text}