"""
learning.py — self-learning from manager procurement decisions

Every time a manager approves, rejects, or modifies an order on WhatsApp,
that decision is stored in procurement_decisions. This module reads those
decisions and writes calibrated per-store settings back to store_config so
the agent gets smarter with every interaction.

What it learns:
  • qty_adjustment_ratio  — managers consistently order 80% of suggested qty?
                            next suggestions are pre-adjusted.
  • approval_rate         — low rate means the agent is over-alerting;
                            raises the reorder threshold automatically.
  • flagged_suppliers     — suppliers rejected 3+ times get flagged so the
                            agent stops suggesting them in favour of alternatives.
  • preferred_suppliers   — suppliers consistently chosen are promoted.

Call run_learning_pass() from agent.py once per scheduled run.
"""

import logging
from datetime import datetime
from collections import Counter

logger = logging.getLogger(__name__)

MIN_DECISIONS = 10          # minimum sample before adjusting anything
SUPPLIER_FLAG_THRESHOLD = 3  # reject count before flagging a supplier


# ── Per-store analysis ────────────────────────────────────────────

def analyze_store(store_id: str) -> dict:
    """
    Analyse the decision history for one store and return insight dict.
    Returns {} if there is not enough data yet.
    """
    import db

    try:
        r = (
            db.get_db()
            .table("procurement_decisions")
            .select("*")
            .eq("store_id", store_id)
            .order("decided_at", desc=True)
            .limit(200)
            .execute()
        )
        decisions = r.data or []
    except Exception as e:
        logger.error(f"analyze_store fetch {store_id}: {e}")
        return {}

    if len(decisions) < MIN_DECISIONS:
        return {}

    approved  = [d for d in decisions if d["decision"] == "approved"]
    rejected  = [d for d in decisions if d["decision"] == "rejected"]
    modified  = [
        d for d in decisions
        if d["decision"] == "modified"
        and d.get("original_qty") and d.get("revised_qty")
        and d["original_qty"] > 0
    ]

    # ── Qty adjustment ratio ──────────────────────────────────────
    # If managers keep revising down, pre-adjust future suggestions.
    qty_ratios = [d["revised_qty"] / d["original_qty"] for d in modified]
    avg_qty_ratio = round(sum(qty_ratios) / len(qty_ratios), 3) if qty_ratios else 1.0

    # ── Approval rate (low = we're over-alerting) ─────────────────
    approval_rate = round(len(approved) / len(decisions), 3) if decisions else 1.0

    # ── Supplier reputation ───────────────────────────────────────
    # Look up the supplier for each rejected procurement
    rejected_suppliers: Counter = Counter()
    approved_suppliers: Counter = Counter()

    try:
        proc_ids = list({d["procurement_id"] for d in decisions if d.get("procurement_id")})
        if proc_ids:
            # Batch fetch procurement rows
            pr = (
                db.get_db()
                .table("procurement_requests")
                .select("id, supplier")
                .in_("id", proc_ids[:100])   # cap to avoid huge queries
                .execute()
            )
            supplier_map = {row["id"]: row.get("supplier", "") for row in (pr.data or [])}

            for d in rejected:
                sup = supplier_map.get(d.get("procurement_id", ""), "")
                if sup:
                    rejected_suppliers[sup] += 1

            for d in approved:
                sup = supplier_map.get(d.get("procurement_id", ""), "")
                if sup:
                    approved_suppliers[sup] += 1
    except Exception as e:
        logger.warning(f"analyze_store supplier lookup {store_id}: {e}")

    flagged_suppliers   = [s for s, n in rejected_suppliers.items() if n >= SUPPLIER_FLAG_THRESHOLD]
    preferred_suppliers = [
        s for s, n in approved_suppliers.most_common(5)
        if s not in flagged_suppliers
    ]

    return {
        "store_id":           store_id,
        "total_decisions":    len(decisions),
        "approval_rate":      approval_rate,
        "avg_qty_ratio":      avg_qty_ratio,
        "flagged_suppliers":  flagged_suppliers,
        "preferred_suppliers": preferred_suppliers,
        "analyzed_at":        datetime.now().isoformat(),
    }


# ── Store config persistence ──────────────────────────────────────

def save_store_config(insights: dict) -> bool:
    """Write learned insights to store_config table."""
    import db

    if not insights:
        return False
    store_id = insights["store_id"]
    try:
        db.get_db().table("store_config").upsert(
            {
                "store_id":           store_id,
                "qty_adjustment_ratio": insights["avg_qty_ratio"],
                "approval_rate":       insights["approval_rate"],
                "flagged_suppliers":   insights["flagged_suppliers"],
                "preferred_suppliers": insights["preferred_suppliers"],
                "decision_count":      insights["total_decisions"],
                "last_learned_at":     insights["analyzed_at"],
            },
            on_conflict="store_id",
        ).execute()
        logger.info(
            f"Learning updated for {store_id}: "
            f"qty_ratio={insights['avg_qty_ratio']} "
            f"approval={insights['approval_rate']} "
            f"flagged={insights['flagged_suppliers']}"
        )
        return True
    except Exception as e:
        logger.error(f"save_store_config {store_id}: {e}")
        return False


def get_store_config(store_id: str) -> dict:
    """
    Return the learned config for a store.
    Falls back to safe defaults if nothing learned yet.
    """
    import db

    defaults = {
        "qty_adjustment_ratio": 1.0,
        "approval_rate": 1.0,
        "flagged_suppliers": [],
        "preferred_suppliers": [],
    }
    try:
        r = (
            db.get_db()
            .table("store_config")
            .select("*")
            .eq("store_id", store_id)
            .execute()
        )
        if r.data:
            row = r.data[0]
            return {
                "qty_adjustment_ratio": float(row.get("qty_adjustment_ratio") or 1.0),
                "approval_rate":        float(row.get("approval_rate") or 1.0),
                "flagged_suppliers":    row.get("flagged_suppliers") or [],
                "preferred_suppliers":  row.get("preferred_suppliers") or [],
            }
    except Exception as e:
        logger.error(f"get_store_config {store_id}: {e}")
    return defaults


# ── Agent entry point ─────────────────────────────────────────────

def run_learning_pass(stores: list | None = None) -> int:
    """
    Run learning analysis for all active stores (or a provided list).
    Returns the number of stores updated.
    Call this once per agent run from agent.py.
    """
    import db

    if stores is None:
        stores = db.get_all_stores()

    updated = 0
    for store in stores:
        insights = analyze_store(store["id"])
        if insights:
            save_store_config(insights)
            updated += 1
    logger.info(f"Learning pass: {updated}/{len(stores)} stores updated")
    return updated