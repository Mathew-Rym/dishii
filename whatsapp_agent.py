"""
whatsapp_agent.py v10 — Dishii Conversational WhatsApp Agent
Complete rewrite:
- Persistent conversation state (Supabase)
- Confirm-before-act for all procurement changes
- Batch approval handling (APPROVE ALL, APPROVE 1,3)
- Rejection memory with follow-up options
- Full audit trail via procurement_decisions table
"""
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

INTENTS = {
    "critical":      ["critical","urgent","expired","expir","waste","rot"],
    "high":          ["high priority","high risk","low stock","running out","nearly"],
    "healthy":       ["healthy","good","fine","safe","green","ok"],
    "dry_goods":     ["dry goods","dry","cereals","rice","flour","pasta","canned","packaged"],
    "fresh_produce": ["fresh produce","produce","vegetables","fruits","veg","tomato","greens"],
    "fresh_meat":    ["fresh meat","meat","chicken","beef","fish","pork","seafood"],
    "dairy":         ["dairy","milk","yogurt","cheese","cream","butter","mala"],
    "orders":        ["orders needed","reorder","order","procurement","buy","stock up","purchase"],
    "waste":         ["waste risk","waste","loss","spoilage","money at risk","financial"],
    "value":         ["inventory value","total value","stock value","worth","value"],
    "briefing":      ["briefing","summary","report","status","situation","how are we","whats"],
    "help":          ["help","commands","hi","hello","hey","what can you"],
}

def detect_intent(text: str) -> str:
    t = text.lower().strip()
    for intent, keywords in INTENTS.items():
        if any(kw in t for kw in keywords):
            return intent
    return "unknown"


# ── DB helpers ────────────────────────────────────────────────

def _db():
    from supabase import create_client
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def get_store_for_phone(phone: str) -> Optional[Dict]:
    """Find store and manager info for a phone number."""
    import whatsapp as wa
    clean = wa.normalize_phone(phone)
    try:
        db = _db()
        r = db.table("store_managers")\
            .select("store_id,name,role")\
            .eq("phone", clean).eq("is_active", True).execute()
        if not r.data:
            return None
        mgr = r.data[0]
        s   = db.table("stores").select("*")\
            .eq("id", mgr["store_id"]).single().execute()
        return {"store": s.data, "manager": mgr}
    except Exception as e:
        logger.error(f"get_store_for_phone: {e}")
        return None

def get_pending_procurement(store_id: str) -> List[Dict]:
    try:
        r = _db().table("procurement_requests").select("*")\
            .eq("store_id", store_id)\
            .in_("status", ["awaiting_manager","pending"])\
            .order("created_at", desc=False).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_pending_procurement: {e}")
        return []

def get_procurement_by_ref(store_id: str, ref: str) -> Optional[Dict]:
    """Find procurement request by first 8 chars of ID."""
    pending = get_pending_procurement(store_id)
    return next((r for r in pending
                 if str(r["id"])[:8].upper() == ref[:8].upper()), None)

def get_items_by_severity(store_id: str, severity: str) -> List[Dict]:
    try:
        db = _db()
        ur = db.table("inventory_uploads").select("id")\
            .eq("store_id", store_id)\
            .order("uploaded_at", desc=True).limit(1).execute()
        if not ur.data: return []
        uid = ur.data[0]["id"]
        r = db.table("inventory_items").select(
            "product_name,current_stock,stock_days,risk_reason,"
            "supplier,traffic_light,waste_value,inventory_value,is_expired"
        ).eq("upload_id", uid).eq("severity_level", severity)\
         .order("risk_score", desc=True).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_items_by_severity: {e}")
        return []

def get_items_by_category(store_id: str, category: str) -> List[Dict]:
    try:
        db = _db()
        ur = db.table("inventory_uploads").select("id")\
            .eq("store_id", store_id)\
            .order("uploaded_at", desc=True).limit(1).execute()
        if not ur.data: return []
        uid = ur.data[0]["id"]
        r = db.table("inventory_items").select("*")\
            .eq("upload_id", uid).eq("category", category)\
            .order("risk_score", desc=True).execute()
        return r.data or []
    except Exception as e:
        return []

def get_financial_summary(store_id: str) -> Dict:
    try:
        r = _db().table("inventory_uploads").select(
            "total_value,waste_value,health_score,total_items,"
            "critical_count,high_count,low_count,uploaded_at"
        ).eq("store_id", store_id)\
         .order("uploaded_at", desc=True).limit(1).execute()
        return r.data[0] if r.data else {}
    except Exception:
        return {}


# ── Format helpers ────────────────────────────────────────────

def format_items(items: List[Dict], title: str, max_items: int = 12) -> str:
    if not items:
        return f"*{title}*\n\nNo items in this category."
    total = len(items)
    lines = [f"*{title}*",
             f"_{total} items · {datetime.now().strftime('%d %b, %H:%M')}_", ""]
    for item in items[:max_items]:
        tl     = item.get("traffic_light","")
        name   = item.get("product_name","?")
        stock  = int(item.get("current_stock",0) or 0)
        days   = int(item.get("stock_days",0) or 0)
        reason = item.get("risk_reason","")
        lines.append(f"{tl} *{name}*: {stock} units ({days}d) — {reason}")
    if total > max_items:
        lines.append(f"\n_{total-max_items} more items. Ask for a report._")
    waste = sum(float(i.get("waste_value",0) or 0) for i in items)
    value = sum(float(i.get("inventory_value",0) or 0) for i in items)
    lines.append(f"\n💰 KES {value:,.0f}  ⚠️ Waste: KES {waste:,.0f}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# PROCUREMENT ACTIONS
# ════════════════════════════════════════════════════════════════

def _do_approve(req: Dict, phone: str, store_id: str, store_name: str) -> bool:
    """Approve a single procurement request and notify supplier."""
    import whatsapp as wa, db, conversation as conv
    try:
        db.approve_procurement(req["id"], wa.normalize_phone(phone))
        conv.log_decision(
            procurement_id   = req["id"],
            store_id         = store_id,
            manager_phone    = wa.normalize_phone(phone),
            decision         = "APPROVED",
            original_qty     = req.get("suggested_qty"),
        )
        if req.get("supplier_phone"):
            sm = wa.msg_supplier_order(store_name, req["product_name"],
                                        req["suggested_qty"], req["id"])
            wa.send(req["supplier_phone"], sm, "supplier_order")
            db.log_whatsapp(store_id, "outbound", req["supplier_phone"],
                            sm, "supplier_order", req["id"])
            db.mark_supplier_notified(req["id"])
        return True
    except Exception as e:
        logger.error(f"_do_approve: {e}")
        return False

def _do_reject(req: Dict, phone: str, store_id: str) -> bool:
    """Reject a procurement request."""
    import whatsapp as wa, db, conversation as conv
    try:
        db.reject_procurement(req["id"], wa.normalize_phone(phone))
        conv.log_decision(
            procurement_id = req["id"],
            store_id       = store_id,
            manager_phone  = wa.normalize_phone(phone),
            decision       = "REJECTED",
            original_qty   = req.get("suggested_qty"),
        )
        return True
    except Exception as e:
        logger.error(f"_do_reject: {e}")
        return False

def handle_batch_reply(phone: str, store_id: str, store_name: str,
                        parsed: Dict) -> str:
    """Handle APPROVE ALL / REJECT ALL / APPROVE 1,3 / REJECT 2."""
    import whatsapp as wa
    pending = get_pending_procurement(store_id)
    if not pending:
        return "No pending procurement approvals right now."

    action    = parsed.get("action", "")
    approved  = []
    rejected  = []
    last_rejected = None

    if action == "APPROVE_ALL":
        for req in pending:
            if _do_approve(req, phone, store_id, store_name):
                approved.append(req["product_name"])

    elif action == "REJECT_ALL":
        for req in pending:
            if _do_reject(req, phone, store_id):
                rejected.append(req["product_name"])
                last_rejected = req

    elif action == "APPROVE_SELECTIVE":
        for idx in parsed.get("indices", []):
            if 1 <= idx <= len(pending):
                req = pending[idx-1]
                if _do_approve(req, phone, store_id, store_name):
                    approved.append(f"{idx}. {req['product_name']}")

    elif action == "REJECT_SELECTIVE":
        for idx in parsed.get("indices", []):
            if 1 <= idx <= len(pending):
                req = pending[idx-1]
                if _do_reject(req, phone, store_id):
                    rejected.append(f"{idx}. {req['product_name']}")
                    last_rejected = req

    lines = []
    if approved:
        lines.append(f"✅ *Approved ({len(approved)}):*\n" + "\n".join(f"• {a}" for a in approved))
    if rejected:
        lines.append(f"❌ *Rejected ({len(rejected)}):*\n" + "\n".join(f"• {r}" for r in rejected))

    # If single rejection, offer follow-up
    if last_rejected and len(rejected) == 1:
        import conversation as conv
        clean = wa.normalize_phone(phone)
        conv.set_state(clean, "awaiting_rejection_reason", store_id, {
            "req_id":      str(last_rejected["id"]),
            "product":     last_rejected["product_name"],
            "original_qty":last_rejected.get("suggested_qty", 0),
            "supplier":    last_rejected.get("supplier","Unknown"),
            "unit_price":  float(last_rejected.get("unit_price",0) or 0),
        })
        follow = wa.msg_rejection_followup(
            last_rejected["product_name"],
            last_rejected["id"],
            last_rejected.get("suggested_qty",0),
            last_rejected.get("supplier","Unknown")
        )
        return "\n\n".join(lines) + "\n\n" + follow

    return "\n\n".join(lines) or "No changes made."


# ════════════════════════════════════════════════════════════════
# REJECTION CONVERSATION FLOW
# ════════════════════════════════════════════════════════════════

def handle_rejection_reason(phone: str, parsed: Dict, ctx: Dict,
                              store_id: str) -> str:
    """
    Manager picked an option (1-4) after rejecting an order.
    We ask for confirmation before doing anything.
    """
    import whatsapp as wa, conversation as conv

    option     = parsed.get("option", 0)
    detail     = parsed.get("detail", "").strip()
    sub_action = parsed.get("sub_action", "")
    req_id     = ctx.get("req_id", "")
    product    = ctx.get("product", "item")
    orig_qty   = int(ctx.get("original_qty", 0))
    supplier   = ctx.get("supplier", "Unknown")
    unit_price = float(ctx.get("unit_price", 0) or 0)
    clean      = wa.normalize_phone(phone)

    # Validate input
    if sub_action == "REDUCE_QTY":
        if not detail.isdigit():
            return "Please provide a number. Example: *1 100* to set quantity to 100."
        new_qty = int(detail)
        if new_qty <= 0:
            return "Quantity must be greater than 0."
        value   = new_qty * unit_price
        change  = f"Reduce from {orig_qty} to {new_qty} units"
        updated = f"{new_qty} units"
        confirm_state = {**ctx, "sub_action": sub_action,
                         "detail": detail, "pending_qty": new_qty}

    elif sub_action == "CHANGE_SUPPLIER":
        if not detail:
            return "Please provide the supplier name. Example: *2 Brookside*"
        change  = f"Change supplier from {supplier} to {detail}"
        updated = detail
        value   = orig_qty * unit_price
        confirm_state = {**ctx, "sub_action": sub_action,
                         "detail": detail, "pending_supplier": detail}

    elif sub_action == "DELAY_ORDER":
        if not detail.isdigit():
            return "Please provide the number of days. Example: *3 3* to delay 3 days."
        days    = int(detail)
        change  = f"Delay order by {days} days"
        updated = f"{days} days"
        value   = orig_qty * unit_price
        confirm_state = {**ctx, "sub_action": sub_action,
                         "detail": detail, "delay_days": days}

    elif sub_action == "CANCEL":
        change  = "Cancel order completely"
        updated = "Cancelled"
        value   = 0
        confirm_state = {**ctx, "sub_action": "CANCEL", "detail": ""}

    else:
        return "Invalid option. Reply 1, 2, 3, or 4."

    # Store state awaiting confirmation
    conv.set_state(clean, "awaiting_update_confirm", store_id, confirm_state)

    return wa.msg_update_confirm(
        product         = product,
        change_desc     = change,
        original        = f"{orig_qty} units · {supplier}",
        updated         = updated,
        estimated_value = value,
        ref_id          = req_id
    )


def handle_update_confirm(phone: str, parsed: Dict, ctx: Dict,
                           store_id: str, store_name: str) -> str:
    """
    Manager said YES or NO to a pending update confirmation.
    YES → apply the change, notify supplier.
    NO  → cancel the update, offer alternatives.
    """
    import whatsapp as wa, db, conversation as conv

    clean      = wa.normalize_phone(phone)
    action     = parsed.get("action", "")
    sub_action = ctx.get("sub_action", "")
    req_id     = ctx.get("req_id", "")
    product    = ctx.get("product", "item")
    supplier   = ctx.get("supplier","Unknown")

    # Always clear state regardless of YES/NO
    conv.clear_state(clean)

    if action != "YES":
        # Manager said NO — offer alternatives
        return wa.msg_update_cancelled(product)

    # Apply the confirmed change
    try:
        if sub_action == "REDUCE_QTY":
            new_qty = int(ctx.get("detail", ctx.get("pending_qty", 0)))
            orig    = ctx.get("original_qty", 0)
            _db().table("procurement_requests").update({
                "suggested_qty": new_qty,
                "total_value":   new_qty * float(ctx.get("unit_price",0) or 0),
                "status":        "awaiting_manager"
            }).eq("id", req_id).execute()
            conv.log_decision(req_id, store_id, clean, "REDUCE_QTY",
                              original_qty=int(orig), revised_qty=new_qty)
            action_desc = f"Quantity updated to {new_qty} units. Re-pending approval."

        elif sub_action == "CHANGE_SUPPLIER":
            new_sup = ctx.get("detail", ctx.get("pending_supplier",""))
            orig_sup= ctx.get("supplier","")
            _db().table("procurement_requests").update({
                "supplier": new_sup,
                "status":   "awaiting_manager"
            }).eq("id", req_id).execute()
            conv.log_decision(req_id, store_id, clean, "CHANGE_SUPPLIER",
                              original_supplier=orig_sup, revised_supplier=new_sup)
            action_desc = f"Supplier changed to {new_sup}. Re-pending approval."

        elif sub_action == "DELAY_ORDER":
            from datetime import timedelta
            days     = int(ctx.get("detail", ctx.get("delay_days", 1)))
            new_date = (datetime.utcnow() + timedelta(days=days)).isoformat()
            _db().table("procurement_requests").update({
                "status":       "delayed",
                "responded_at": new_date
            }).eq("id", req_id).execute()
            conv.log_decision(req_id, store_id, clean, "DELAY_ORDER",
                              delay_days=days)
            action_desc = f"Order delayed by {days} days."

        elif sub_action == "CANCEL":
            _db().table("procurement_requests").update({
                "status":           "rejected",
                "manager_response": "CANCELLED",
                "manager_phone":    clean,
                "responded_at":     datetime.utcnow().isoformat()
            }).eq("id", req_id).execute()
            conv.log_decision(req_id, store_id, clean, "CANCEL")
            action_desc = "Order cancelled."

        else:
            return "Update applied."

        return wa.msg_update_confirmed(product, action_desc)

    except Exception as e:
        logger.error(f"handle_update_confirm: {e}")
        return "Failed to apply update. Please contact your admin."


# ════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ════════════════════════════════════════════════════════════════

def handle_incoming_message(from_phone: str, message_text: str) -> Optional[str]:
    import whatsapp as wa
    import conversation as conv

    if not message_text or not message_text.strip():
        return None

    clean = wa.normalize_phone(from_phone)
    info  = get_store_for_phone(clean)

    if not info:
        return (
            "I don't recognise this number.\n\n"
            "Ask your store manager to add your number to Dishii."
        )

    store      = info["store"]
    manager    = info["manager"]
    store_id   = store["id"]
    store_name = store["name"]
    mgr_name   = manager.get("name","Manager")
    role       = manager.get("role","manager")

    parsed = wa.parse_manager_reply(message_text)

    # ── Check active conversation state ──────────────────────
    state_data = conv.get_state(clean)
    if state_data:
        state   = state_data.get("state","")
        ctx     = state_data.get("context", {})

        if state == "awaiting_rejection_reason":
            if parsed.get("action") == "REJECTION_FOLLOWUP":
                return handle_rejection_reason(clean, parsed, ctx, store_id)
            # User typed something else — offer options again
            return (
                f"Please reply with:\n"
                f"*1 [qty]* — e.g. `1 50`\n"
                f"*2 [supplier]* — e.g. `2 Brookside`\n"
                f"*3 [days]* — e.g. `3 3`\n"
                f"*4* — cancel order\n\n"
                f"Or type *cancel* to exit"
            )

        if state == "awaiting_update_confirm":
            if message_text.strip().lower() == "cancel":
                conv.clear_state(clean)
                return "Update cancelled. Order unchanged."
            return handle_update_confirm(clean, parsed, ctx, store_id, store_name)

    # ── Batch procurement actions ─────────────────────────────
    BATCH_ACTIONS = {"APPROVE_ALL","REJECT_ALL","APPROVE_SELECTIVE","REJECT_SELECTIVE"}
    if parsed.get("action") in BATCH_ACTIONS:
        if role == "supervisor":
            return "⛔ Your role doesn't have procurement authority. Contact your manager."
        return handle_batch_reply(clean, store_id, store_name, parsed)

    # ── Single YES/NO with ref ────────────────────────────────
    if parsed.get("action") == "YES" and parsed.get("ref_id"):
        req = get_procurement_by_ref(store_id, parsed["ref_id"])
        if req:
            _do_approve(req, clean, store_id, store_name)
            return wa.msg_procurement_approved(
                req["product_name"], req["suggested_qty"],
                req.get("supplier","Unknown"),
                float(req.get("total_value",0)), req["id"]
            )
        return f"Order {parsed['ref_id'][:8].upper()} not found or already actioned."

    if parsed.get("action") == "NO" and parsed.get("ref_id"):
        req = get_procurement_by_ref(store_id, parsed["ref_id"])
        if req:
            _do_reject(req, clean, store_id)
            # Set conversation state for follow-up
            conv.set_state(clean, "awaiting_rejection_reason", store_id, {
                "req_id":      str(req["id"]),
                "product":     req["product_name"],
                "original_qty":req.get("suggested_qty",0),
                "supplier":    req.get("supplier","Unknown"),
                "unit_price":  float(req.get("unit_price",0) or 0),
            })
            return wa.msg_rejection_followup(
                req["product_name"], req["id"],
                req.get("suggested_qty",0),
                req.get("supplier","Unknown")
            )
        return f"Order {parsed['ref_id'][:8].upper()} not found."

    # ── Inventory queries ─────────────────────────────────────
    intent = detect_intent(message_text)

    ROLE_PERMISSIONS = {
        "owner":      ["critical","high","healthy","dry_goods","fresh_produce",
                       "fresh_meat","dairy","orders","waste","value","briefing","help"],
        "manager":    ["critical","high","healthy","dry_goods","fresh_produce",
                       "fresh_meat","dairy","orders","waste","value","briefing","help"],
        "supervisor": ["critical","high","orders","help"],
    }
    allowed = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["supervisor"])

    if intent not in allowed and intent != "unknown":
        return f"⛔ Your role ({role}) doesn't have access to {intent} reports."

    if intent == "help":
        return (
            f"👋 *Hi {mgr_name}!*\n\n"
            f"*Inventory:*\n"
            f"• critical items\n• high priority items\n• healthy items\n\n"
            f"*Category reports:*\n"
            f"• fresh produce · fresh meat · dairy · dry goods\n\n"
            f"*Procurement:*\n"
            f"• orders needed\n"
            f"• APPROVE ALL / REJECT ALL\n"
            f"• APPROVE 1,3 · REJECT 2\n\n"
            f"*Financial:*\n"
            f"• waste risk · inventory value\n\n"
            f"*Full briefing:*\n"
            f"• briefing\n\n"
            f"_Role: {role.title()} · {store_name}_"
        )

    if intent == "critical":
        return format_items(get_items_by_severity(store_id,"CRITICAL"),
                            f"🔴 Critical — {store_name}")

    if intent == "high":
        return format_items(get_items_by_severity(store_id,"HIGH"),
                            f"🟠 High Priority — {store_name}")

    if intent == "healthy":
        return format_items(get_items_by_severity(store_id,"LOW"),
                            f"🟢 Healthy — {store_name}", 20)

    if intent == "fresh_produce":
        return format_items(get_items_by_category(store_id,"fresh_produce"),
                            f"Fresh Produce — {store_name}")

    if intent == "fresh_meat":
        return format_items(get_items_by_category(store_id,"fresh_meat"),
                            f"Fresh Meat — {store_name}")

    if intent == "dairy":
        return format_items(get_items_by_category(store_id,"dairy"),
                            f"Dairy — {store_name}")

    if intent == "dry_goods":
        return format_items(get_items_by_category(store_id,"dry_goods"),
                            f"Dry Goods — {store_name}", 20)

    if intent == "orders":
        pending = get_pending_procurement(store_id)
        if not pending:
            return f"No pending orders for {store_name}. All stock levels are healthy."
        return wa.msg_batch_procurement(store_name, pending)

    if intent in ("waste","value"):
        summ  = get_financial_summary(store_id)
        tv    = float(summ.get("total_value",0) or 0)
        waste = float(summ.get("waste_value",0) or 0)
        hs    = summ.get("health_score",0)
        crit  = summ.get("critical_count",0)
        up    = (summ.get("uploaded_at","")[:10]) or "unknown"
        pct   = round(waste/tv*100,1) if tv>0 else 0
        actions = []
        if crit > 0: actions.append(f"• Action {crit} critical items immediately")
        if waste > 50000: actions.append(f"• Consider markdowns on expiring stock")
        if not actions: actions.append("• All metrics within healthy range")
        return (
            f"*Financial Summary — {store_name}*\n_{up}_\n\n"
            f"📦 Value: *KES {tv:,.0f}*\n"
            f"⚠️ Waste Risk: *KES {waste:,.0f}* ({pct}%)\n"
            f"❤️ Health: *{hs}%*\n"
            f"🔴 Critical: {crit}\n\n"
            f"*Actions:*\n" + "\n".join(actions)
        )

    if intent == "briefing":
        from ai import generate_briefing
        import whatsapp as wa
        summ    = get_financial_summary(store_id)
        crit    = get_items_by_severity(store_id,"CRITICAL")
        expired = [i for i in crit if i.get("is_expired")]
        reorder = [i for i in crit if not i.get("is_expired")]
        watch   = get_items_by_severity(store_id,"HIGH")[:3]
        br      = generate_briefing(store_name, summ, crit)
        return wa.msg_operational_briefing(
            store_name, summ, expired, reorder,
            reorder[:5], watch, br
        )

    # Unknown
    return (
        "I didn't understand that.\n\n"
        "Type *help* to see all available commands."
    )


# ── Webhook processor ─────────────────────────────────────────

def process_webhook(payload: dict) -> dict:
    import whatsapp as wa

    event = payload.get("event","")
    data  = payload.get("data",{})

    if event != "messages.upsert":
        return {"action":"ignored","reason":f"event={event}"}

    msg_text   = (data.get("message",{}).get("conversation") or
                  data.get("message",{}).get("extendedTextMessage",{}).get("text",""))
    from_jid   = data.get("key",{}).get("remoteJid","")
    is_from_me = data.get("key",{}).get("fromMe", True)

    if is_from_me or not msg_text:
        return {"action":"skipped"}

    from_phone = from_jid.replace("@s.whatsapp.net","").replace("@c.us","")
    reply      = handle_incoming_message(from_phone, msg_text)

    if not reply:
        return {"action":"no_reply"}

    ok = wa.send_reply(from_phone, reply)

    try:
        info = get_store_for_phone(from_phone)
        if info:
            import db
            sid = info["store"]["id"]
            db.log_whatsapp(sid,"inbound",from_phone,msg_text,"query")
            db.log_whatsapp(sid,"outbound",from_phone,reply,"query_response")
    except Exception as e:
        logger.error(f"log error: {e}")

    return {"action":"replied","to":from_phone,"sent":ok}


# ── CLI test ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    phone = sys.argv[1] if len(sys.argv) > 1 else ""
    msg   = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "help"
    if not phone:
        print("Usage: python whatsapp_agent.py 254720521291 'critical items'")
        sys.exit(1)
    print(f"From +{phone}: '{msg}'")
    reply = handle_incoming_message(phone, msg)
    print(f"\n--- Reply ---\n{reply}")