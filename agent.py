"""
agent.py v10 — Dishii Autonomous Agent
Fixes: reorder logic (expired never reorder), batch procurement,
       deduplication, new enterprise briefing format
"""
import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

import db
import whatsapp as wa
from ai import generate_briefing, classify_item


def should_send_briefing() -> bool:
    """Send briefing at top of hour (cron runs :00 and :30)."""
    return datetime.now().minute < 35


def process_store(store: dict) -> dict:
    store_id   = store["id"]
    store_name = store["name"]
    stats      = {"alerts":0, "procurement":0, "errors":0}

    logger.info(f"Processing: {store_name}")

    phones = db.get_manager_phones(store_id)
    if not phones:
        logger.warning(f"{store_name}: no active managers — skipping")
        return stats

    items = db.get_latest_inventory(store_id)
    if not items:
        logger.info(f"{store_name}: no inventory loaded")
        return stats

    logger.info(f"{store_name}: {len(items)} items")

    # ── Reclassify all items with fresh expiry dates ──────────
    expired_items  = []   # is_expired = True → REMOVE
    reorder_items  = []   # should_reorder = True → ORDER
    watch_items    = []   # HIGH severity → monitor
    critical_items = []   # CRITICAL or HIGH → include in briefing

    for item in items:
        import pandas as pd
        from ai import days_until
        dte  = days_until(pd.to_datetime(item.get("expiry_date"), errors="coerce"))
        item["days_to_expiry"] = dte

        cls = classify_item(item)

        # Queue for batch update
        item["_cls"] = cls

        item.update(cls)

        # Categorize correctly
        if cls["is_expired"]:
            expired_items.append(item)  # Remove from shelf

        elif wa.should_reorder(item):   # FIX: only genuine stockouts
            reorder_items.append(item)  # Order more

        elif cls["severity_level"] == "HIGH":
            watch_items.append(item)    # Monitor

        if cls["severity_level"] in ("CRITICAL","HIGH"):
            critical_items.append(item)

    # Batch update all items at once
    try:
        updates = []
        for item in items:
            cls = item.get("_cls", {})
            if cls:
                updates.append({
                    "id": item["id"],
                    "days_to_expiry":   item.get("days_to_expiry"),
                    "stock_days":       cls.get("stock_days"),
                    "waste_value":      cls.get("waste_value"),
                    "inventory_value":  cls.get("inventory_value"),
                    "traffic_light":    cls.get("traffic_light"),
                    "severity_level":   cls.get("severity_level"),
                    "risk_type":        cls.get("risk_type"),
                    "risk_score":       cls.get("risk_score"),
                    "risk_reason":      cls.get("risk_reason"),
                    "risk_color":       cls.get("risk_color"),
                    "order_required":   cls.get("order_required"),
                    "is_expired":       cls.get("is_expired"),
                    "show_in_priority": cls.get("show_in_priority"),
                    "updated_at":       datetime.now().isoformat()
                })
        # Batch upsert
        if updates:
            db.get_db().table("inventory_items").upsert(updates).execute()
            logger.info(f"{store_name}: batch updated {len(updates)} items")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Batch update failed: {e}")

    # Batch update all items at once
    try:
        updates = []
        for item in items:
            cls = item.get("_cls", {})
            if cls:
                updates.append({
                    "id": item["id"],
                    "days_to_expiry":   item.get("days_to_expiry"),
                    "stock_days":       cls.get("stock_days"),
                    "waste_value":      cls.get("waste_value"),
                    "inventory_value":  cls.get("inventory_value"),
                    "traffic_light":    cls.get("traffic_light"),
                    "severity_level":   cls.get("severity_level"),
                    "risk_type":        cls.get("risk_type"),
                    "risk_score":       cls.get("risk_score"),
                    "risk_reason":      cls.get("risk_reason"),
                    "risk_color":       cls.get("risk_color"),
                    "order_required":   cls.get("order_required"),
                    "is_expired":       cls.get("is_expired"),
                    "show_in_priority": cls.get("show_in_priority"),
                    "updated_at":       datetime.now().isoformat()
                })
        # Batch upsert
        if updates:
            db.get_db().table("inventory_items").upsert(updates).execute()
            logger.info(f"{store_name}: batch updated {len(updates)} items")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Batch update failed: {e}")

    logger.info(
        f"{store_name}: {len(expired_items)} expired, "
        f"{len(reorder_items)} need reorder, "
        f"{len(watch_items)} watch"
    )

    # ── Build summary ─────────────────────────────────────────
    summary = {
        "total":       len(items),
        "critical":    sum(1 for i in items if i.get("severity_level")=="CRITICAL"),
        "high":        sum(1 for i in items if i.get("severity_level")=="HIGH"),
        "medium":      sum(1 for i in items if i.get("severity_level")=="MEDIUM"),
        "low":         sum(1 for i in items if i.get("severity_level")=="LOW"),
        "total_value": sum(float(i.get("inventory_value",0) or 0) for i in items),
        "waste_value": sum(float(i.get("waste_value",0) or 0) for i in items),
    }
    tv = summary["total_value"]
    summary["health_score"] = max(0,min(100,int(100-(summary["waste_value"]/tv*100)))) if tv>0 else 100

    # ── Create procurement requests (FIXED: never for expired) ─
    existing_pending = {r["product_name"] for r in db.get_pending_procurement(store_id)}
    new_proc_items   = []

    for item in reorder_items[:10]:
        # Double-check: skip expired, waste, overstocked
        if item.get("is_expired"):
            logger.info(f"Skip expired from procurement: {item['product_name']}")
            continue
        if item.get("risk_type") in ("WASTE","OVERSTOCK"):
            continue
        if item["product_name"] in existing_pending:
            continue

        rate  = float(item.get("daily_sales_rate", 1) or 1)
        qty   = max(1, int(rate * 14))  # 2-week supply
        req_id = db.create_procurement_request(store_id, item, qty)
        if req_id:
            stats["procurement"] += 1
            item["_req_id"] = req_id
            new_proc_items.append(item)

    # ── Send BATCHED procurement approval ─────────────────────
    if new_proc_items:
        batch_msg = wa.msg_batch_procurement(store_name, new_proc_items)
        sent = wa.send_to_all(phones, batch_msg, "procurement")
        if sent:
            stats["alerts"] += sent
            db.log_whatsapp(store_id,"outbound",",".join(phones),
                            batch_msg,"procurement")
            logger.info(f"{store_name}: sent batch of {len(new_proc_items)} procurement items")

    # ── Hourly briefing (top of hour only) ────────────────────
    if should_send_briefing():
        logger.info(f"{store_name}: generating operational briefing")

        ai_text = generate_briefing(store_name, summary, critical_items)

        briefing_msg = wa.msg_operational_briefing(
            store_name        = store_name,
            summary           = summary,
            expired_items     = expired_items,
            reorder_items     = reorder_items,
            procurement_queue = reorder_items[:5],
            watch_items       = watch_items,
            briefing_text     = ai_text
        )

        sent = wa.send_to_all(phones, briefing_msg, "briefing")
        if sent:
            stats["alerts"] += sent
            db.log_whatsapp(store_id,"outbound",",".join(phones),
                            briefing_msg,"briefing")
            logger.info(f"{store_name}: briefing sent to {sent} managers")

    logger.info(
        f"{store_name}: done — "
        f"alerts={stats['alerts']}, proc={stats['procurement']}, "
        f"errors={stats['errors']}"
    )
    return stats


def run():
    start = time.time()
    logger.info("═══ Dishii Agent v10 ═══")

    status = wa.get_connection_status()
    logger.info(f"WhatsApp: {status}")
    if status != "open":
        logger.warning("WhatsApp offline — alerts will not be delivered")

    stores = db.get_all_stores()
    logger.info(f"Stores: {len(stores)}")

    if not stores:
        logger.info("No stores — nothing to do")
        db.log_agent_run("scheduled",0,0,0,0,time.time()-start)
        return

    total_alerts = total_proc = 0
    errors = []

    for store in stores:
        try:
            s = process_store(store)
            total_alerts += s["alerts"]
            total_proc   += s["procurement"]
            if s["errors"]:
                errors.append(f"{store['name']}: {s['errors']} errors")
        except Exception as e:
            msg = f"{store['name']}: {e}"
            logger.error(f"Store failed: {msg}")
            errors.append(msg)

    duration = time.time() - start
    db.log_agent_run(
        run_type           = "scheduled",
        stores_checked     = len(stores),
        alerts_sent        = total_alerts,
        procurement_created= total_proc,
        items_processed    = 0,
        duration           = duration,
        errors             = "; ".join(errors) if errors else ""
    )

    logger.info(
        f"═══ Done {duration:.1f}s · "
        f"stores={len(stores)} · alerts={total_alerts} · "
        f"proc={total_proc} · errors={len(errors)} ═══"
    )


if __name__ == "__main__":
    run()