"""
Dishii v9.0 — Production Dashboard
Persistent header · Role-based WhatsApp · Clash prevention · Reports on every tab
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io, os, base64, logging
from datetime import datetime
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore")

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import db
import whatsapp as wa
from ai import process_upload, df_to_db_rows, generate_briefing

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="Dishii",
    page_icon="🍔",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.main .block-container{padding-top:0 !important;max-width:1500px;}
[data-testid="stSidebar"]{background:#080f1a;border-right:1px solid #1a2535;}
footer{visibility:hidden;}#MainMenu{visibility:hidden;}
/* Auto-refresh indicator */
.refresh-bar{font-size:0.6rem;color:#475569;text-align:right;padding:2px 8px;}

/* ── Persistent header ── */
.op-header{
  background:linear-gradient(135deg,#080f1a 0%,#0d1e38 100%);
  border-bottom:1px solid #1a3050;
  padding:0.75rem 1.5rem;
  display:flex; align-items:center; justify-content:space-between;
  gap:1rem; flex-wrap:wrap;
  position:sticky; top:0; z-index:100;
}
.op-store{display:flex;align-items:center;gap:10px;}
.op-store-name{font-size:1.05rem;font-weight:700;color:#f1f5f9;}
.op-store-meta{font-size:0.65rem;color:#64748b;}
.op-badge{display:inline-block;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);
  color:#10b981;font-size:0.6rem;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;
  padding:2px 8px;border-radius:12px;}
.op-kpis{display:flex;gap:1.5rem;align-items:center;}
.op-kpi{text-align:center;}
.op-kpi-val{font-size:1.4rem;font-weight:700;line-height:1;}
.op-kpi-lbl{font-size:0.58rem;color:#64748b;text-transform:uppercase;letter-spacing:0.8px;}
.op-kpi.red .op-kpi-val{color:#f87171;}
.op-kpi.amber .op-kpi-val{color:#fbbf24;}
.op-kpi.green .op-kpi-val{color:#34d399;}
.op-kpi.blue .op-kpi-val{color:#60a5fa;}
.op-health{display:flex;flex-direction:column;gap:3px;}
.op-health-bar{width:120px;height:6px;background:#1a2f4a;border-radius:3px;overflow:hidden;}
.op-health-fill{height:100%;border-radius:3px;transition:width 0.5s;}
.op-sync{font-size:0.62rem;color:#475569;}

/* ── Cards ── */
.icard{background:#0d1b2e;border:1px solid #1a2f4a;border-radius:12px;
  padding:0.875rem 1rem;margin-bottom:0.625rem;border-left:3px solid;transition:background 0.15s;}
.icard:hover{background:#0f2040;}
.icard-title{font-size:0.88rem;font-weight:600;color:#e2e8f0;}
.icard-reason{font-size:0.7rem;color:#94a3b8;margin-top:0.2rem;}
.icard-meta{font-size:0.65rem;color:#475569;margin-top:0.35rem;}
.icard-locked{opacity:0.6;pointer-events:none;}

/* ── KPI grid ── */
.kgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin:1rem 0 1.25rem;}
.kpi{background:#0d1b2e;border:1px solid #1a2f4a;border-radius:14px;padding:1.1rem 1.4rem;transition:border-color 0.2s;}
.kpi:hover{border-color:#10b981;}
.kpi-label{font-size:0.62rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:1.2px;}
.kpi-value{font-size:1.9rem;font-weight:700;margin:0.2rem 0;}
.kpi-sub{font-size:0.65rem;color:#475569;}
.kpi.red{border-color:rgba(220,38,38,0.3);}.kpi.red .kpi-value{color:#f87171;}
.kpi.amber{border-color:rgba(245,158,11,0.3);}.kpi.amber .kpi-value{color:#fbbf24;}
.kpi.green{border-color:rgba(16,185,129,0.3);}.kpi.green .kpi-value{color:#34d399;}
.kpi.blue{border-color:rgba(59,130,246,0.3);}.kpi.blue .kpi-value{color:#60a5fa;}

.sdiv{border-top:1px solid #1a2535;margin:0.75rem 0;}

.stTabs [data-baseweb="tab-list"]{background:#0d1b2e;border-radius:10px;padding:4px;gap:3px;border:1px solid #1a2f4a;}
.stTabs [data-baseweb="tab"]{border-radius:7px;font-weight:500;color:#64748b;font-size:0.82rem;padding:7px 18px;}
.stTabs [aria-selected="true"]{background:#10b981 !important;color:white !important;}
.stProgress>div>div{background:#10b981;}
div[data-testid="stMetricValue"]{font-size:1.4rem;font-weight:700;color:#f1f5f9;}
.stButton button{border-radius:8px;font-weight:500;font-size:0.82rem;}
</style>
""", unsafe_allow_html=True)

# ── Logo ──────────────────────────────────────────────────────
def load_logo():
    for p in ["assets/dishii-logo.png","dishii-logo.png"]:
        if os.path.exists(p):
            with open(p,"rb") as f: return base64.b64encode(f.read()).decode()
    return ""
LOGO = load_logo()

# ── Cached DB calls ───────────────────────────────────────────
@st.cache_data(ttl=30)
def cached_wa_status():
    return wa.get_connection_status()

@st.cache_data(ttl=10)
def cached_stores():
    return db.get_all_stores()

@st.cache_data(ttl=10)
def cached_managers(sid):
    return db.get_managers(sid)

@st.cache_data(ttl=10)
def cached_inventory(sid):
    return db.get_latest_inventory(sid)

@st.cache_data(ttl=10)
def cached_procurement(sid):
    return db.get_all_procurement(sid, limit=50)

@st.cache_data(ttl=10)
def cached_wa_logs(sid):
    return db.get_whatsapp_logs(sid, limit=50)

@st.cache_data(ttl=30)
def cached_last_run():
    return db.get_last_agent_run()

# Auto-refresh every 30 seconds
import time as _time
# Auto-refresh handled inside app flow

WA_STATUS = cached_wa_status()
WA_LIVE   = WA_STATUS == "open"


# ── Role-based message routing ────────────────────────────────

ROLE_SEND = {
    "owner":      ["alert","procurement","briefing","upload_alert","query_response","supplier_order","critical_summary","financial_summary"],
    "manager":    ["alert","procurement","briefing","upload_alert","query_response","supplier_order"],
    "supervisor": ["alert","query_response"],
}

def get_phones_for_type(store_id: str, msg_type: str) -> list:
    """Return phones of managers who should receive this message type."""
    managers = db.get_managers(store_id)
    phones   = []
    for m in managers:
        role    = m.get("role","manager")
        allowed = ROLE_SEND.get(role, ROLE_SEND["supervisor"])
        if msg_type in allowed and m.get("phone"):
            phones.append(m["phone"])
    return phones

def wa_send_typed(store_id: str, text: str, msg_type: str,
                   procurement_id: str = None) -> int:
    """Send WhatsApp to the right managers based on message type and role."""
    phones = get_phones_for_type(store_id, msg_type)
    sent   = 0
    for phone in phones:
        if wa.send(phone, text):
            sent += 1
    if phones:
        db.log_whatsapp(store_id, "outbound", ",".join(phones), text, msg_type, procurement_id)
    return sent


# ── Report generators ─────────────────────────────────────────

def make_excel_report(df: pd.DataFrame, store_name: str, sheet_name: str = "Inventory") -> bytes:
    """Generate a styled Excel report."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet_name)
        # Summary sheet
        if "severity_level" in df.columns:
            summ = df.groupby("severity_level").agg(
                count=("product_name","count"),
                total_value=("inventory_value","sum"),
                waste_value=("waste_value","sum")
            ).reset_index()
            summ.to_excel(w, index=False, sheet_name="Summary")
    return buf.getvalue()

def make_procurement_excel(items: list, store_name: str) -> bytes:
    """Excel report for procurement."""
    rows = []
    for item in items:
        rate = float(item.get("daily_sales_rate",1) or 1)
        qty  = max(1, int(rate * 14))
        rows.append({
            "Product":            item.get("product_name",""),
            "Supplier":           item.get("supplier","Unknown"),
            "Supplier Phone":     item.get("supplier_phone",""),
            "Current Stock":      int(item.get("current_stock",0) or 0),
            "Days Left":          int(item.get("stock_days",0) or 0),
            "Suggested Order Qty":qty,
            "Unit Price (KES)":   float(item.get("selling_price",0) or 0),
            "Order Value (KES)":  round(qty * float(item.get("selling_price",0) or 0), 2),
            "Severity":           item.get("severity_level",""),
            "Risk Reason":        item.get("risk_reason",""),
        })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, index=False, sheet_name="Procurement Orders")
    return buf.getvalue()

def report_filename(store_name: str, report_type: str) -> str:
    return f"dishii_{store_name.replace(' ','_')}_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


# ── Persistent operational header ────────────────────────────

def render_header(store, items, summary, last_upload):
    """Renders sticky operational header — always visible regardless of tab."""
    if not store or not items:
        return
    hs    = summary.get("health_score", 0)
    hc    = "#10b981" if hs >= 70 else "#f59e0b" if hs >= 40 else "#ef4444"
    hpct  = hs

    if LOGO:
        logo_html = f'<img src="data:image/png;base64,{LOGO}" width="28" style="border-radius:6px;vertical-align:middle;">'
    else:
        logo_html = "🍔"

    st.markdown(f"""
    <div class="op-header">
        <div class="op-store">
            {logo_html}
            <div>
                <div class="op-store-name">{store['name']}</div>
                <div class="op-store-meta">
                    <span class="op-badge">{store.get('store_type','supermarket')}</span>
                    &nbsp; {store.get('location','—')} &nbsp;·&nbsp;
                    {len(db.get_managers(store['id']))} managers &nbsp;·&nbsp;
                    {len(items)} SKUs
                </div>
            </div>
        </div>
        <div class="op-kpis">
            <div class="op-kpi red">
                <div class="op-kpi-val">{summary['critical']}</div>
                <div class="op-kpi-lbl">Critical</div>
            </div>
            <div class="op-kpi amber">
                <div class="op-kpi-val">{summary['high']}</div>
                <div class="op-kpi-lbl">High</div>
            </div>
            <div class="op-kpi green">
                <div class="op-kpi-val">{summary['low']}</div>
                <div class="op-kpi-lbl">Healthy</div>
            </div>
            <div class="op-kpi blue">
                <div class="op-kpi-val">{sum(1 for i in items if i.get('order_required'))}</div>
                <div class="op-kpi-lbl">Orders</div>
            </div>
        </div>
        <div class="op-health">
            <div style="font-size:0.7rem;color:#94a3b8;margin-bottom:2px;">Health {hpct}%</div>
            <div class="op-health-bar">
                <div class="op-health-fill" style="width:{hpct}%;background:{hc};"></div>
            </div>
            <div class="op-sync">
                KES {summary['total_value']:,.0f} value &nbsp;·&nbsp;
                KES {summary['waste_value']:,.0f} at risk
            </div>
            <div class="op-sync">Last upload: {last_upload}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════
with st.sidebar:
    if LOGO:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:0.75rem 0 0.5rem;">'
            f'<img src="data:image/png;base64,{LOGO}" width="36" style="border-radius:9px;">'
            f'<div><div style="font-size:1.1rem;font-weight:700;color:#f1f5f9;">Dishii</div>'
            f'<div style="font-size:0.58rem;color:#475569;letter-spacing:1.5px;text-transform:uppercase;">Food Operations</div></div>'
            f'</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:1.2rem;font-weight:700;color:#f1f5f9;padding:0.75rem 0;">Dishii</div>', unsafe_allow_html=True)

    wa_dot = "#10b981" if WA_LIVE else "#f59e0b"
    st.markdown(
        f'<div style="font-size:0.7rem;color:#64748b;line-height:2.2;margin:0.25rem 0;">'
        f'<span style="color:{wa_dot};">&#9679;</span> WhatsApp: {"Live" if WA_LIVE else "Offline"}<br>'
        f'<span style="color:#10b981;">&#9679;</span> Database: Connected'
        f'</div>', unsafe_allow_html=True)
    st.markdown('<div class="sdiv"></div>', unsafe_allow_html=True)

    stores    = cached_stores()
    store_map = {s["id"]: s["name"] for s in stores}
    st.markdown('<div style="font-size:0.68rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.4rem;">Active Store</div>', unsafe_allow_html=True)
    if store_map:
        selected_id = st.selectbox("store", list(store_map.keys()),
            format_func=lambda x: store_map[x], label_visibility="collapsed", key="active_store")
        mgrs_count = len(cached_managers(selected_id))
        st.markdown(f'<div style="font-size:0.68rem;color:#475569;">{mgrs_count} manager{"s" if mgrs_count!=1 else ""}</div>', unsafe_allow_html=True)
    else:
        selected_id = None
        st.markdown('<div style="font-size:0.75rem;color:#475569;padding:0.4rem 0;">No stores — create one in Stores tab</div>', unsafe_allow_html=True)

    st.markdown('<div class="sdiv"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.68rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.5rem;">Thresholds</div>', unsafe_allow_html=True)
    red_t   = st.slider("Critical expiry (days)", 1, 30,  7)
    amber_t = st.slider("High expiry (days)",     1, 60, 14)
    stock_w = st.slider("Stock warning (days)",   1, 30, 14)
    show_n  = st.slider("Priority items shown",   5, 50, 15)

    st.markdown('<div class="sdiv"></div>', unsafe_allow_html=True)
    last_run = cached_last_run()
    if last_run:
        ran = last_run.get("ran_at","")[:16].replace("T"," ")
        st.markdown(
            f'<div style="font-size:0.65rem;color:#475569;line-height:1.8;">'
            f'Agent last ran<br><span style="color:#64748b;">{ran}</span><br>'
            f'Alerts: {last_run.get("alerts_sent",0)} &nbsp; Orders: {last_run.get("procurement_created",0)}'
            f'</div>', unsafe_allow_html=True)
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ════════════════════════════════════════════════════════════════
# LOAD ACTIVE STORE DATA (shared across all tabs)
# ════════════════════════════════════════════════════════════════
active_store  = db.get_store_by_id(selected_id) if selected_id else None
active_items  = cached_inventory(selected_id)   if selected_id else []
active_mgrs   = cached_managers(selected_id)    if selected_id else []

active_summary = {
    "total":   len(active_items),
    "critical":sum(1 for i in active_items if i.get("severity_level")=="CRITICAL"),
    "high":    sum(1 for i in active_items if i.get("severity_level")=="HIGH"),
    "medium":  sum(1 for i in active_items if i.get("severity_level")=="MEDIUM"),
    "low":     sum(1 for i in active_items if i.get("severity_level")=="LOW"),
    "total_value":sum(float(i.get("inventory_value",0) or 0) for i in active_items),
    "waste_value":sum(float(i.get("waste_value",0) or 0) for i in active_items),
}
tv = active_summary["total_value"]
active_summary["health_score"] = max(0,min(100,int(100-(active_summary["waste_value"]/tv*100)))) if tv>0 else 100

try:
    ur = db.get_db().table("inventory_uploads").select("uploaded_at").eq("store_id",selected_id).order("uploaded_at",desc=True).limit(1).execute() if selected_id else None
    last_upload = ur.data[0]["uploaded_at"][:16].replace("T"," ") if ur and ur.data else "Never"
except Exception:
    last_upload = "Unknown"

# ── Render persistent header ──────────────────────────────────
if active_store and active_items:
    render_header(active_store, active_items, active_summary, last_upload)
elif active_store:
    st.markdown(
        f'<div class="op-header"><div class="op-store">'
        f'<div class="op-store-name">{active_store["name"]}</div>'
        f'<div class="op-store-meta"><span class="op-badge">{active_store.get("store_type","supermarket")}</span>'
        f' &nbsp; {active_store.get("location","—")} &nbsp;·&nbsp; No inventory yet</div>'
        f'</div></div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# MAIN TABS
# ════════════════════════════════════════════════════════════════
t_dash, t_stores, t_upload, t_proc, t_wa = st.tabs([
    "Dashboard", "Stores & Managers", "Upload Inventory", "Procurement", "WhatsApp Log"
])


# ══════════════════════════════════ DASHBOARD ══════════════════
with t_dash:
    if not selected_id:
        c1,c2,c3 = st.columns(3)
        for col,num,title,sub in [
            (c1,"01","Create a store","Go to Stores & Managers tab"),
            (c2,"02","Upload inventory","Go to Upload Inventory tab"),
            (c3,"03","Agent activates","Runs every 30 min, alerts sent automatically"),
        ]:
            col.markdown(f'<div class="kpi blue"><div class="kpi-label">Step {num}</div><div class="kpi-value" style="font-size:1rem;color:#f1f5f9;margin:0.3rem 0;">{title}</div><div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True)
    elif not active_items:
        st.info("No inventory loaded for this store. Go to Upload Inventory tab.")
    else:
        df_live = pd.DataFrame(active_items)
        s       = active_summary

        # Action row
        cb1, cb2, cb3 = st.columns([1,1,4])
        with cb1:
            if st.button("Send Briefing", type="primary", use_container_width=True):
                with st.spinner("Generating AI briefing..."):
                    crit = [i for i in active_items if i.get("severity_level") in ("CRITICAL","HIGH")]
                    br   = generate_briefing(active_store["name"], s, crit)
                # Owner gets summary, Manager gets full operational briefing
                owner_msg = (
                    f"*Business Summary — {active_store['name']}*\n"
                    f"Health: {s['health_score']}% | Value: KES {s['total_value']:,.0f}\n"
                    f"Critical: {s['critical']} | Waste risk: KES {s['waste_value']:,.0f}\n\n{br}"
                )
                mgr_msg = wa.msg_hourly_briefing(active_store["name"], br, s)
                # Send based on role
                for m in active_mgrs:
                    role = m.get("role","manager")
                    msg  = owner_msg if role == "owner" else mgr_msg
                    if m.get("phone") and "briefing" in ROLE_SEND.get(role,[]):
                        wa.send(m["phone"], msg)
                db.log_whatsapp(selected_id,"outbound",
                                ",".join([m["phone"] for m in active_mgrs if m.get("phone")]),
                                mgr_msg,"briefing")
                st.toast("Briefing sent to managers")
                st.cache_data.clear()
        with cb2:
            if st.button("Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        st.markdown(f"""
        <div class="kgrid">
            <div class="kpi red"><div class="kpi-label">Critical</div><div class="kpi-value">{s['critical']}</div><div class="kpi-sub">Act immediately</div></div>
            <div class="kpi amber"><div class="kpi-label">High</div><div class="kpi-value">{s['high']}</div><div class="kpi-sub">Address today</div></div>
            <div class="kpi green"><div class="kpi-label">Healthy</div><div class="kpi-value">{s['low']}</div><div class="kpi-sub">No action needed</div></div>
            <div class="kpi blue"><div class="kpi-label">Orders Needed</div><div class="kpi-value">{sum(1 for i in active_items if i.get('order_required'))}</div><div class="kpi-sub">Procurement required</div></div>
        </div>""", unsafe_allow_html=True)

        st.markdown('<div class="sdiv"></div>', unsafe_allow_html=True)
        d1,d2,d3 = st.tabs(["Priority Actions","Analytics","Full Inventory"])

        with d1:
            prio = [i for i in active_items if i.get("show_in_priority")][:show_n]
            if prio:
                st.markdown(f"**{len(prio)} items — highest risk first**")
                for item in prio:
                    color = item.get("risk_color","#dc2626")
                    tl    = item.get("traffic_light","")
                    pc,pb = st.columns([5,1])
                    with pc:
                        st.markdown(
                            f'<div class="icard" style="border-left-color:{color};">'
                            f'<div class="icard-title">{tl}&nbsp; {item["product_name"]}</div>'
                            f'<div class="icard-reason">{item.get("risk_reason","")}</div>'
                            f'<div class="icard-meta">'
                            f'Supplier: {item.get("supplier","Unknown")} &middot; '
                            f'Stock: {int(item.get("current_stock",0))} units &middot; '
                            f'Waste: KES {float(item.get("waste_value",0)):,.0f} &middot; '
                            f'{item.get("stock_action","")}'
                            f'</div></div>', unsafe_allow_html=True)
                    with pb:
                        if item.get("order_required"):
                            if st.button("Alert", key=f"al_{item['id']}", use_container_width=True):
                                msg = wa.msg_stock_alert(active_store["name"],item["product_name"],
                                    item["severity_level"],int(item.get("current_stock",0)),
                                    int(item.get("stock_days",0)),item.get("risk_reason",""))
                                sent = wa_send_typed(selected_id, msg, "alert")
                                st.success(f"Sent to {sent} manager(s)")
                                st.cache_data.clear()
            else:
                st.success("All inventory is healthy.")

            # Download priority report
            if prio:
                prio_df = pd.DataFrame(prio)
                show_cols = [c for c in ["product_name","category","traffic_light","severity_level","days_to_expiry","current_stock","stock_days","risk_reason","waste_value","inventory_value","supplier","stock_action"] if c in prio_df.columns]
                st.download_button("Download Priority Report",
                    data=make_excel_report(prio_df[show_cols], active_store["name"], "Priority Items"),
                    file_name=report_filename(active_store["name"],"priority"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        with d2:
            c1,c2 = st.columns(2)
            with c1:
                rdf = pd.DataFrame([{"Level":"Critical","Count":s["critical"]},{"Level":"High","Count":s["high"]},{"Level":"Medium","Count":s["medium"]},{"Level":"Low","Count":s["low"]}])
                rdf = rdf[rdf["Count"]>0]
                if not rdf.empty:
                    fig = px.pie(rdf,names="Level",values="Count",hole=0.5,color="Level",
                                 color_discrete_map={"Critical":"#dc2626","High":"#f59e0b","Medium":"#eab308","Low":"#10b981"})
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",font=dict(color="#94a3b8",family="Inter"),margin=dict(l=0,r=0,t=10,b=0))
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "category" in df_live.columns:
                    cat = df_live.groupby("category").agg(value=("inventory_value","sum"),waste=("waste_value","sum")).reset_index()
                    if not cat.empty:
                        fig2 = px.bar(cat,x="category",y=["value","waste"],barmode="group",color_discrete_map={"value":"#3b82f6","waste":"#dc2626"})
                        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",font=dict(color="#94a3b8",family="Inter"))
                        st.plotly_chart(fig2, use_container_width=True)

        with d3:
            show_cols = [c for c in ["product_name","category","traffic_light","severity_level","days_to_expiry","current_stock","stock_days","risk_reason","discount_percent","inventory_value","waste_value","supplier"] if c in df_live.columns]
            disp = df_live[show_cols].copy()
            if "risk_score" in df_live.columns:
                disp = disp.assign(_s=df_live["risk_score"]).sort_values("_s",ascending=False).drop(columns=["_s"])
            st.dataframe(disp.head(200), use_container_width=True, height=450,
                column_config={
                    "inventory_value":st.column_config.NumberColumn("Value (KES)",format="KES %.0f"),
                    "waste_value":    st.column_config.NumberColumn("Waste (KES)", format="KES %.0f"),
                    "discount_percent":st.column_config.NumberColumn("Discount %",format="%.0f%%"),
                    "stock_days":     st.column_config.NumberColumn("Stock Days",  format="%.1f"),
                    "days_to_expiry": st.column_config.NumberColumn("Exp. Days",   format="%d"),
                    "current_stock":  st.column_config.NumberColumn("Stock",       format="%.0f"),
                })
            st.download_button("Download Full Inventory Report",
                data=make_excel_report(disp, active_store["name"] if active_store else "store"),
                file_name=report_filename(active_store["name"] if active_store else "store","full_inventory"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════ STORES & MANAGERS ══════════
with t_stores:
    st.markdown("### Stores & Managers")
    st.caption("Each store is fully isolated. All managers stored in database — no hardcoded numbers.")

    # ── Section 1: Create new store ──────────────────────────
    st.markdown("#### Create New Store")
    with st.form("new_store_form", clear_on_submit=False):
        col_a, col_b, col_c = st.columns(3)
        with col_a: s_name = st.text_input("Store name *", placeholder="e.g. Quikmart Westlands")
        with col_b: s_loc  = st.text_input("Location",     placeholder="Westlands, Nairobi")
        with col_c: s_type = st.selectbox("Type", ["supermarket","mini_mart","restaurant","distributor","pharmacy"])

        st.markdown("**Managers** (1 required, up to 4 — any country phone number)")
        m_cols = st.columns(4)
        mgr_inputs = []
        for i, col in enumerate(m_cols, 1):
            with col:
                req = " *" if i == 1 else ""
                mn = st.text_input(f"Name{req}", key=f"ns_mn{i}", placeholder="Full name")
                mp = st.text_input(f"Phone{req}", key=f"ns_mp{i}", placeholder="+254... or +1... or +44...")
                mr = st.selectbox("Role", ["manager","owner","supervisor"], key=f"ns_mr{i}")
                if mn.strip() and mp.strip():
                    mgr_inputs.append({"name":mn.strip(),"phone":mp.strip(),"role":mr})

        if st.form_submit_button("Create Store", type="primary"):
            if not s_name.strip():
                st.error("Store name required")
            elif not mgr_inputs:
                st.error("Add at least 1 manager with name and phone")
            else:
                try:
                    new_store = db.create_store(s_name.strip(), s_loc.strip(), s_type)
                    if new_store:
                        for m in mgr_inputs:
                            db.add_manager(new_store["id"], m["name"], m["phone"], m["role"])
                            clean = m["phone"].replace("+","").replace(" ","").replace("-","")
                            wa.send(clean, wa.msg_welcome(s_name.strip(), m["name"]))
                        st.success(f"✅ Store '{s_name}' created! Switching now...")
                        st.session_state["active_store"] = new_store["id"]
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Failed to create store — db returned None")
                except Exception as e:
                    st.error(f"Error creating store: {e}")

    st.markdown('<div class="sdiv"></div>', unsafe_allow_html=True)

    # ── Section 2: Existing stores ───────────────────────────
    st.markdown("#### Your Stores")
    all_s = cached_stores()
    if not all_s:
        st.markdown('<div style="color:#475569;font-size:0.85rem;">No stores yet.</div>', unsafe_allow_html=True)
    else:
        for s in all_s:
            ml      = cached_managers(s["id"])
            is_sel  = s["id"] == selected_id
            bc      = "#10b981" if is_sel else "#1a2f4a"
            has_inv = len(cached_inventory(s["id"])) > 0
            mgr_txt = " &middot; ".join([f"{m['name']} ({m.get('role','mgr')}) +{m['phone']}" for m in ml]) or "No managers"

            st.markdown(
                f'<div class="icard" style="border-left-color:{bc};">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<div class="icard-title">{"✓ " if is_sel else ""}{s["name"]}</div>'
                f'<div style="font-size:0.65rem;color:{"#10b981" if has_inv else "#475569"};">{"Inventory loaded" if has_inv else "No inventory"}</div></div>'
                f'<div class="icard-reason">{s.get("location","—")} &middot; {s.get("store_type","—")}</div>'
                f'<div class="icard-meta">{mgr_txt}</div>'
                f'</div>', unsafe_allow_html=True)

            # List managers with remove buttons
            ml2 = cached_managers(s["id"])
            if ml2:
                with st.expander(f"Managers ({len(ml2)}) — {s['name']}"):
                    for m in ml2:
                        c1, c2 = st.columns([5,1])
                        with c1:
                            st.markdown(f"**{m['name']}** · {m.get('role','manager').title()} · +{m['phone']}")
                        with c2:
                            if st.button("✕", key=f"rm_{m['id']}", help=f"Remove {m['name']}"):
                                db.get_db().table("store_managers").update({"is_active": False}).eq("id", m["id"]).execute()
                                st.success(f"Removed {m['name']}")
                                st.cache_data.clear()
                                st.rerun()

            # Add manager to existing store
            with st.expander(f"Add manager to {s['name']}"):
                with st.form(f"add_mgr_{s['id']}"):
                    ac1,ac2,ac3 = st.columns(3)
                    with ac1: am_n = st.text_input("Name *",  key=f"amn_{s['id']}")
                    with ac2: am_p = st.text_input("Phone *", key=f"amp_{s['id']}", placeholder="+254... or +1... or +44...")
                    with ac3: am_r = st.selectbox("Role", ["manager","owner","supervisor"], key=f"amr_{s['id']}")
                    if st.form_submit_button("Add Manager", type="primary"):
                        if am_n.strip() and am_p.strip():
                            db.add_manager(s["id"], am_n.strip(), am_p.strip(), am_r)
                            clean = am_p.replace("+","").replace(" ","").replace("-","")
                            wa.send(clean, wa.msg_welcome(s["name"], am_n.strip()))
                            st.success(f"{am_n} added as {am_r}. Welcome message sent.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Name and phone required")


# ══════════════════════════════════ UPLOAD ═════════════════════
with t_upload:
    st.markdown("### Upload Inventory")
    st.caption("Upload Excel or CSV. Columns auto-detected. Duplicate uploads blocked by file hash.")

    all_stores_up = cached_stores()
    if not all_stores_up:
        st.warning("Create a store first.")
    else:
        # Default to currently selected store
        default_idx = next((i for i,s in enumerate(all_stores_up) if s["id"]==selected_id), 0)
        t_id    = st.selectbox("Upload for:", [s["id"] for s in all_stores_up],
                               index=default_idx,
                               format_func=lambda x: next(s["name"] for s in all_stores_up if s["id"]==x),
                               key="upload_target")
        t_store = db.get_store_by_id(t_id)

        with st.expander("Expected column format"):
            st.dataframe(pd.DataFrame({
                "product_name":["Tomatoes","Milk 500ml","Chicken Breast","Rice 2kg"],
                "expiry_date":["2026-05-22","2026-05-20","2026-05-19","2026-12-31"],
                "current_stock":[50,200,30,500],"daily_sales_rate":[12,20,8,10],
                "supplier":["Fresh Farms","DairyCo","Kenchic","Rice Millers"],
                "selling_price":[120,65,350,180],"supplier_phone":["254712000001","","254712000003",""],
            }), use_container_width=True)

        uf = st.file_uploader("Choose file", type=["xlsx","csv","xls"])
        if uf is not None:
            fbytes = uf.getvalue(); fhash = db.file_hash(fbytes); uf.seek(0)
            if db.is_already_processed(fhash, t_id):
                st.warning("This exact file was already uploaded. Modify it or upload a new one.")
            else:
                st.info(f"Ready: **{uf.name}** for **{t_store['name']}**")
                if st.button("Process & Upload", type="primary"):
                    with st.spinner(f"Processing {uf.name}..."):
                        try:
                            uf.seek(0)
                            raw = pd.read_excel(uf) if not uf.name.lower().endswith(".csv") else pd.read_csv(uf)
                            if raw.empty: st.error("File is empty")
                            else:
                                uid  = db.create_upload_record(t_id, uf.name, fhash)
                                df_p, summ = process_upload(raw, t_id, uid, red_t, amber_t, stock_w)
                                db.update_upload_summary(uid, summ)
                                rows = df_to_db_rows(df_p, t_id, uid)
                                if db.insert_inventory_items(rows):
                                    st.success(f"{len(rows)} SKUs saved for **{t_store['name']}**")
                                    c1,c2,c3,c4 = st.columns(4)
                                    c1.metric("SKUs",    summ["total"])
                                    c2.metric("Critical",summ["critical"])
                                    c3.metric("Orders",  int(df_p["order_required"].sum()) if "order_required" in df_p.columns else 0)
                                    c4.metric("Health",  f"{summ['health_score']}%")

                                    # Send alerts based on roles
                                    if "severity_level" in df_p.columns:
                                        crit_i = df_p[df_p["severity_level"].isin(["CRITICAL","HIGH"])].to_dict("records")
                                    else:
                                        crit_i = []
                                    with st.spinner("AI briefing..."):
                                        br = generate_briefing(t_store["name"], summ, crit_i)

                                    # Manager message
                                    mgr_msg = (f"Inventory Loaded — {t_store['name']}\n"
                                               f"{len(rows)} SKUs · {summ['critical']} critical · Health: {summ['health_score']}%\n"
                                               f"Waste risk: KES {summ['waste_value']:,.0f}\n\n{br}")
                                    # Owner summary
                                    own_msg = (f"*Upload Summary — {t_store['name']}*\n"
                                               f"Health: {summ['health_score']}% | Value: KES {summ.get('total_value',0):,.0f}\n"
                                               f"Critical: {summ['critical']} items | Waste: KES {summ['waste_value']:,.0f}")

                                    sent = 0
                                    for m in db.get_managers(t_id):
                                        role = m.get("role","manager")
                                        msg  = own_msg if role == "owner" else mgr_msg
                                        if m.get("phone") and "upload_alert" in ROLE_SEND.get(role,["upload_alert"]):
                                            if wa.send(m["phone"].replace("+","").replace(" ",""), msg):
                                                sent += 1
                                    db.log_whatsapp(t_id,"outbound","",mgr_msg,"upload_alert")
                                    if sent: st.info(f"Alert + briefing sent to {sent} manager(s)")

                                    # Procurement requests
                                    if "order_required" in df_p.columns:
                                        pc = 0
                                        for _,row in df_p[df_p["order_required"]==True].head(5).iterrows():
                                            dr  = max(float(row.get("daily_sales_rate",1) or 1), 0.1)
                                            qty = max(1, int(dr*14))
                                            rd  = row.to_dict(); rd["upload_id"] = uid
                                            rid = db.create_procurement_request(t_id, rd, qty)
                                            if rid:
                                                pc += 1
                                                val = qty * float(row.get("selling_price",0) or 0)
                                                pm  = wa.msg_procurement_request(t_store["name"],row["product_name"],qty,row.get("supplier","Unknown"),val,rid,row.get("severity_level","HIGH"))
                                                wa_send_typed(t_id, pm, "procurement", rid)
                                        if pc: st.info(f"{pc} procurement requests sent")

                                    # Download upload report
                                    show_cols_up = [c for c in ["product_name","category","traffic_light","severity_level","days_to_expiry","current_stock","stock_days","risk_reason","inventory_value","waste_value","supplier"] if c in df_p.columns]
                                    st.download_button("Download Upload Report",
                                        data=make_excel_report(df_p[show_cols_up], t_store["name"], "Upload Report"),
                                        file_name=report_filename(t_store["name"],"upload"),
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                                    st.cache_data.clear()
                                else:
                                    st.error("Failed to save to database")
                        except Exception as e:
                            st.error(f"Upload failed: {e}")
                            logger.error(f"Upload error: {e}", exc_info=True)


# ══════════════════════════════════ PROCUREMENT ════════════════
with t_proc:
    st.markdown("### Procurement")
    st.caption("First action wins. Conflicts are automatically blocked with an audit trail.")

    if not selected_id:
        st.info("Select a store from the sidebar.")
    else:
        pending  = db.get_pending_procurement(selected_id)
        all_p    = cached_procurement(selected_id)
        orders_i = [i for i in active_items if i.get("order_required")]

        cp, ch2 = st.columns([3,2], gap="large")

        with cp:
            st.markdown(f"**Pending approvals ({len(pending)})**")
            if not pending:
                st.markdown('<div style="color:#475569;font-size:0.85rem;">No pending approvals.</div>', unsafe_allow_html=True)
            else:
                for req in pending:
                    # Check if already actioned (clash prevention)
                    current_status = req.get("status","awaiting_manager")
                    is_locked = current_status not in ("awaiting_manager","pending")

                    uc  = {"CRITICAL":"#dc2626","HIGH":"#f59e0b"}.get(req.get("urgency","HIGH"),"#f59e0b")
                    sw  = " · Supplier on WhatsApp" if req.get("supplier_phone") else ""
                    lock_class = " icard-locked" if is_locked else ""

                    st.markdown(
                        f'<div class="icard{lock_class}" style="border-left-color:{uc};">'
                        f'<div class="icard-title">{req["product_name"]}'
                        f'{"  🔒 Locked" if is_locked else ""}</div>'
                        f'<div class="icard-reason">Order: {req["suggested_qty"]} units &middot; KES {float(req.get("total_value",0)):,.0f}<br>'
                        f'Supplier: {req.get("supplier","Unknown")}{sw}</div>'
                        f'<div class="icard-meta">Ref: {str(req["id"])[:8].upper()}'
                        + (f' · Actioned by {req.get("manager_phone","?")} at {(req.get("responded_at","") or "")[:16]}' if is_locked else "")
                        + '</div></div>', unsafe_allow_html=True)

                    if not is_locked:
                        phones = db.get_manager_phones(selected_id)
                        ca, cr = st.columns(2)
                        with ca:
                            if st.button("Approve", key=f"y_{req['id']}", type="primary", use_container_width=True):
                                # Re-fetch to check for clash
                                fresh = db.get_db().table("procurement_requests").select("status","manager_phone","responded_at").eq("id",req["id"]).single().execute()
                                if fresh.data and fresh.data["status"] not in ("awaiting_manager","pending"):
                                    st.warning(f"Already actioned by {fresh.data.get('manager_phone','?')} — cannot change.")
                                else:
                                    db.approve_procurement(req["id"], phones[0] if phones else "dashboard")
                                    if req.get("supplier_phone"):
                                        sm = wa.msg_supplier_order(active_store["name"],req["product_name"],req["suggested_qty"],req["id"])
                                        wa.send(req["supplier_phone"], sm)
                                        db.log_whatsapp(selected_id,"outbound",req["supplier_phone"],sm,"supplier_order",req["id"])
                                        db.mark_supplier_notified(req["id"])
                                    cm = wa.msg_procurement_approved(req["product_name"],req["suggested_qty"],req.get("supplier","Unknown"),float(req.get("total_value",0)),req["id"])
                                    wa_send_typed(selected_id, cm, "procurement")
                                    st.success("Approved — supplier notified")
                                    st.cache_data.clear(); st.rerun()
                        with cr:
                            if st.button("Reject", key=f"n_{req['id']}", use_container_width=True):
                                fresh = db.get_db().table("procurement_requests").select("status","manager_phone").eq("id",req["id"]).single().execute()
                                if fresh.data and fresh.data["status"] not in ("awaiting_manager","pending"):
                                    st.warning(f"Already actioned by {fresh.data.get('manager_phone','?')}.")
                                else:
                                    db.reject_procurement(req["id"], phones[0] if phones else "dashboard")
                                    rm = wa.msg_procurement_rejected(req["product_name"],req["id"])
                                    wa_send_typed(selected_id, rm, "procurement")
                                    st.info("Rejected")
                                    st.cache_data.clear(); st.rerun()

            # Download procurement report
            if orders_i:
                st.markdown("---")
                st.download_button("Download Procurement Report",
                    data=make_procurement_excel(orders_i, active_store["name"] if active_store else "store"),
                    file_name=report_filename(active_store["name"] if active_store else "store","procurement"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        with ch2:
            st.markdown("**Order history**")
            if not all_p:
                st.markdown('<div style="color:#475569;font-size:0.85rem;">No orders yet.</div>', unsafe_allow_html=True)
            else:
                for req in all_p[:25]:
                    sc = {"approved":"#10b981","rejected":"#ef4444","supplier_notified":"#3b82f6","awaiting_manager":"#f59e0b"}.get(req.get("status",""),"#475569")
                    responded = req.get("manager_phone","")
                    resp_time = (req.get("responded_at","") or "")[:16].replace("T"," ")
                    st.markdown(
                        f'<div class="icard" style="border-left-color:{sc};padding:0.55rem 0.875rem;">'
                        f'<div style="font-size:0.82rem;font-weight:600;color:#e2e8f0;">{req["product_name"]}</div>'
                        f'<div style="font-size:0.65rem;color:#64748b;margin-top:0.2rem;">'
                        f'{req.get("suggested_qty",0)} units &middot; {req.get("status","?").replace("_"," ").title()}'
                        + (f' &middot; by +{responded}' if responded and responded != "dashboard" else "")
                        + (f' at {resp_time}' if resp_time else "")
                        + '</div></div>', unsafe_allow_html=True)

            # Download order history
            if all_p:
                hist_df = pd.DataFrame(all_p)[["product_name","supplier","suggested_qty","total_value","status","manager_response","manager_phone","responded_at","created_at"]].copy()
                hist_buf = io.BytesIO()
                with pd.ExcelWriter(hist_buf, engine="openpyxl") as w:
                    hist_df.to_excel(w, index=False, sheet_name="Order History")
                st.download_button("Download Order History",
                    data=hist_buf.getvalue(),
                    file_name=report_filename(active_store["name"] if active_store else "store","order_history"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════ WHATSAPP LOG ══════════════
with t_wa:
    st.markdown("### WhatsApp Log")
    wa_c  = "#10b981" if WA_LIVE else "#f59e0b"
    wa_d  = "Connected — messages delivered to real phones" if WA_LIVE else "Not connected — check EVOLUTION_URL and EVOLUTION_KEY"
    st.markdown(
        f'<div class="icard" style="border-left-color:{wa_c};">'
        f'<div class="icard-title" style="color:{wa_c};">WhatsApp: {WA_STATUS.replace("_"," ").title()}</div>'
        f'<div class="icard-reason">{wa_d}</div>'
        f'<div class="icard-meta">Conversational agent active — managers can text to query inventory data</div>'
        f'</div>', unsafe_allow_html=True)

    # Conversational agent info
    with st.expander("How to query via WhatsApp"):
        st.markdown("""
        Managers can text the connected WhatsApp number and ask:
        
        **Inventory queries:** `critical items` · `high priority items` · `healthy items`
        
        **Category reports:** `fresh produce report` · `fresh meat report` · `dairy report` · `dry goods report`
        
        **Procurement:** `orders needed`
        
        **Financial:** `waste risk` · `inventory value`
        
        **Full briefing:** `briefing` or `send me a briefing`
        
        **Access:** Only registered managers can query. Role determines what data they can access.
        """)

    if not selected_id:
        st.info("Select a store to see its WhatsApp log.")
    else:
        logs = cached_wa_logs(selected_id)
        st.markdown(f"**{len(logs)} messages — {store_map.get(selected_id,'')}**")

        if not logs:
            st.markdown('<div style="color:#475569;font-size:0.85rem;padding:0.5rem 0;">No messages yet.</div>', unsafe_allow_html=True)
        else:
            tc = {"alert":"#ef4444","procurement":"#f59e0b","briefing":"#3b82f6",
                  "supplier_order":"#8b5cf6","upload_alert":"#10b981",
                  "query":"#06b6d4","query_response":"#06b6d4"}
            for log in logs:
                direction = log.get("direction","outbound")
                phone     = log.get("to_phone","") if direction=="outbound" else log.get("from_phone","")
                mtype     = log.get("message_type","text")
                sat       = log.get("sent_at","")[:16].replace("T"," ")
                mc        = tc.get(mtype,"#475569")
                arrow     = "→" if direction=="outbound" else "←"
                text      = log.get("message_text","")
                bg        = "#0d2535" if direction=="inbound" else "#0d1b2e"
                radius    = "10px 10px 10px 0" if direction=="inbound" else "0 10px 10px 10px"
                # Find manager name for this phone
                mgr_name  = next((m["name"] for m in active_mgrs if m.get("phone","").replace("+","") == phone.replace("+","")), None)
                mgr_tag   = f' · <span style="color:#10b981;font-weight:500;">{mgr_name}</span>' if mgr_name else ""
                st.markdown(
                    f'<div style="margin-bottom:0.75rem;">'
                    f'<div style="font-size:0.62rem;color:#475569;margin-bottom:3px;">'
                    f'{sat} &nbsp;<span style="color:{mc};font-weight:500;">{mtype}</span>&nbsp; {arrow} +{phone}{mgr_tag}</div>'
                    f'<div style="background:{bg};border:1px solid #1a2f4a;border-radius:{radius};'
                    f'padding:0.65rem 0.9rem;font-size:0.78rem;color:#cbd5e1;white-space:pre-wrap;">'
                    f'{text[:500]}{"..." if len(text)>500 else ""}'
                    f'</div></div>', unsafe_allow_html=True)

            # Download WhatsApp log
            log_df = pd.DataFrame(logs)
            log_buf = io.BytesIO()
            with pd.ExcelWriter(log_buf, engine="openpyxl") as w:
                log_df.to_excel(w, index=False, sheet_name="WhatsApp Log")
            st.download_button("Download WhatsApp Log",
                data=log_buf.getvalue(),
                file_name=report_filename(store_map.get(selected_id,"store"),"whatsapp_log"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")