"""
patch_ux_fixes.py — three fixes in one:
  1. WhatsApp status shows live truth (not stale cached value)
  2. Dashboard auto-refreshes when inventory is present but cache is stale
  3. Dishii brand colors (#6366f1 indigo) for all buttons and sliders

Run from /workspaces/dishii:
    python3 patch_ux_fixes.py
"""
import io, py_compile

def read(p): return io.open(p, encoding="utf-8").read()
def write(p, s): io.open(p, "w", encoding="utf-8").write(s); print(f"   patched {p}")

# ─────────────────────────────────────────────────
# 1.  whatsapp.py — fresh env in get_connection_status
# ─────────────────────────────────────────────────
wa = read("whatsapp.py")

old_status = '''def get_connection_status() -> str:
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
    return "disconnected"'''

new_status = '''def get_connection_status() -> str:
    """Always reads fresh env so the status reflects reality, not a stale import."""
    from dotenv import load_dotenv as _ld; _ld(override=True)
    _url  = os.getenv("EVOLUTION_URL", "").rstrip("/")
    _key  = os.getenv("EVOLUTION_KEY", "")
    _inst = os.getenv("EVOLUTION_INSTANCE", "dishii")
    if not _url or not _key:
        return "not_configured"
    try:
        r = requests.get(
            f"{_url}/instance/connectionState/{_inst}",
            headers={"apikey": _key, "Content-Type": "application/json"},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            # Evolution API v2 returns {"instance":{"state":"open"}} or {"state":"open"}
            state = (data.get("instance", {}).get("state")
                     or data.get("state", "unknown"))
            return state
    except Exception:
        pass
    return "disconnected"'''

if old_status in wa:
    wa = wa.replace(old_status, new_status)
    print("   whatsapp.py: get_connection_status reads fresh env")
else:
    print("   whatsapp.py: anchor not found — skipping (may already be patched)")

write("whatsapp.py", wa)

# ─────────────────────────────────────────────────
# 2.  app.py — brand colors CSS + auto-refresh
# ─────────────────────────────────────────────────
app = read("app.py")

# 2a. Brand colors — extend the existing .stButton rule
old_btn_css = ".stButton button{border-radius:8px;font-weight:500;font-size:0.82rem;}"
new_btn_css = """.stButton button{border-radius:8px;font-weight:500;font-size:0.82rem;}
/* ── Dishii brand colors ────────────────────────────── */
button[data-testid="baseButton-primary"],
.stButton > button[kind="primary"]{
    background:#6366f1 !important;border-color:#6366f1 !important;color:#fff !important;}
button[data-testid="baseButton-primary"]:hover,
.stButton > button[kind="primary"]:hover{
    background:#4f46e5 !important;border-color:#4f46e5 !important;}
button[data-testid="baseButton-secondary"],
.stButton > button[kind="secondary"]{
    border-color:#1e293b !important;color:#94a3b8 !important;}
/* Slider thumb + filled track */
[data-testid="stSlider"] [role="slider"]{
    background:#6366f1 !important;border-color:#6366f1 !important;}
[data-testid="stSlider"] div[data-testid="stTickBarMin"],
[data-testid="stSlider"] div[class*="Track"]:first-child{
    background:#6366f1 !important;}
[data-testid="stSlider"] span{color:#6366f1 !important;font-weight:600;}
/* Active tab keeps green (matches brand) */
.stTabs [aria-selected="true"]{background:#10b981 !important;color:white !important;}"""

if old_btn_css in app:
    app = app.replace(old_btn_css, new_btn_css)
    print("   app.py: Dishii brand colors injected")
else:
    print("   app.py: button CSS anchor not found — skipping")

# 2b. Reduce wa status cache TTL so it reflects reality quickly
old_wa_ttl = "@st.cache_data(ttl=30)\ndef cached_wa_status():\n    return wa.get_connection_status()"
new_wa_ttl = "@st.cache_data(ttl=8)\ndef cached_wa_status():\n    return wa.get_connection_status()"
if old_wa_ttl in app:
    app = app.replace(old_wa_ttl, new_wa_ttl)
    print("   app.py: WhatsApp status cache TTL → 8s")

# 2c. Auto-refresh dashboard when inventory is present but cache shows empty
old_active = "active_items  = cached_inventory(selected_id)   if selected_id else []"
new_active  = (
    "active_items  = cached_inventory(selected_id)   if selected_id else []\n"
    "# Auto-refresh once per store if items are empty but may exist in DB\n"
    "if selected_id and not active_items:\n"
    "    _rkey = f\"_inv_refresh_{selected_id}\"\n"
    "    if not st.session_state.get(_rkey):\n"
    "        st.session_state[_rkey] = True\n"
    "        st.cache_data.clear()\n"
    "        st.rerun()\n"
    "else:\n"
    "    st.session_state.pop(f\"_inv_refresh_{selected_id}\", None) if selected_id else None"
)
if old_active in app:
    app = app.replace(old_active, new_active)
    print("   app.py: auto-refresh inventory on stale cache")
else:
    print("   app.py: auto-refresh anchor not found — skipping")

write("app.py", app)

# ─────────────────────────────────────────────────
# 3.  Compile check
# ─────────────────────────────────────────────────
ok = True
for f in ["whatsapp.py", "app.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print(f"   OK  {f}")
    except py_compile.PyCompileError as e:
        print(f"   FAIL {f}: {e}")
        ok = False

print()
print("✅ Done — restart Streamlit to apply." if ok else "⚠️  Fix errors above.")