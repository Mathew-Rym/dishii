"""
patch_upload_ui.py — adds Google Sheets section to the upload tab in app.py
while keeping the manual file upload exactly as it is.

Run from /workspaces/dishii:
  python3 patch_upload_ui.py
"""
import io, sys

def read(p): return io.open(p, encoding="utf-8").read()
def write(p, s): io.open(p, "w", encoding="utf-8").write(s); print(f"   patched {p}")

# ── 1. Add sheets_connector import to app.py ─────────────────────
src = read("app.py")

import_anchor = "import db\nimport whatsapp as wa\nfrom ai import process_upload, df_to_db_rows, generate_briefing"
import_with_sheets = (
    "import db\n"
    "import whatsapp as wa\n"
    "from ai import process_upload, df_to_db_rows, generate_briefing\n"
    "try:\n"
    "    import sheets_connector as _sc\n"
    "    _SHEETS_ENABLED = True\n"
    "except ImportError:\n"
    "    _sc = None\n"
    "    _SHEETS_ENABLED = False\n"
)
if "sheets_connector" not in src:
    assert import_anchor in src, f"import anchor not found"
    src = src.replace(import_anchor, import_with_sheets)
    print("   app.py: added sheets_connector import")
else:
    print("   app.py: import already present (skip)")

# ── 2. Insert Sheets UI between t_store line and column-format expander ──
anchor = (
    "        t_store = db.get_store_by_id(t_id)\n"
    "\n"
    "        with st.expander(\"Expected column format\"):"
)

sheets_ui = (
    "        t_store = db.get_store_by_id(t_id)\n"
    "\n"
    "        # ════════════════════════════════════════════════════\n"
    "        # GOOGLE SHEETS AUTO-SYNC\n"
    "        # ════════════════════════════════════════════════════\n"
    "        _sheet_url_saved = _sc.get_store_sheet(t_id) if _SHEETS_ENABLED else None\n"
    "        _sheet_connected = bool(_sheet_url_saved)\n"
    "        _expander_label  = (\n"
    "            \"🟢 Google Sheet connected — auto-syncs every 30 min\"\n"
    "            if _sheet_connected else\n"
    "            \"🔗 Connect Google Sheet (auto-sync, no manual uploads needed)\"\n"
    "        )\n"
    "        with st.expander(_expander_label, expanded=not _sheet_connected):\n"
    "            if not _SHEETS_ENABLED:\n"
    "                st.warning(\"sheets_connector.py not found — copy it into the project folder.\")\n"
    "            elif _sheet_connected:\n"
    "                st.success(f\"`{(_sheet_url_saved or '')[:80]}`\")\n"
    "                _col_sync, _col_disc = st.columns([3, 1])\n"
    "                with _col_sync:\n"
    "                    if st.button(\"🔄 Sync now\", key=f\"sync_now_{t_id}\"):\n"
    "                        with st.spinner(\"Pulling latest data from sheet…\"):\n"
    "                            _df_sheet = _sc.pull_sheet(_sheet_url_saved)\n"
    "                        if _df_sheet is None or _df_sheet.empty:\n"
    "                            st.error(\"Could not read the sheet — check permissions.\")\n"
    "                        else:\n"
    "                            _sh = _sc.sheet_hash(_df_sheet)\n"
    "                            if db.is_already_processed(_sh, t_id):\n"
    "                                st.info(\"Sheet hasn't changed since last sync — nothing to do.\")\n"
    "                            else:\n"
    "                                _uid = db.create_upload_record(\n"
    "                                    t_id, f\"{t_store['name']}_sheets_manual.csv\", _sh\n"
    "                                )\n"
    "                                if not _uid:\n"
    "                                    st.error(\"Could not create upload record.\")\n"
    "                                else:\n"
    "                                    _df_p, _summ = process_upload(\n"
    "                                        _df_sheet, t_id, _uid, red_t, amber_t, stock_w\n"
    "                                    )\n"
    "                                    db.update_upload_summary(_uid, _summ)\n"
    "                                    _rows = df_to_db_rows(_df_p)\n"
    "                                    if db.insert_inventory_items(_rows):\n"
    "                                        db.cleanup_old_uploads(t_id, keep=3)\n"
    "                                        _sc.mark_synced(t_id, \"ok\")\n"
    "                                        st.success(\n"
    "                                            f\"✅ Synced {len(_rows)} SKUs from sheet\"\n"
    "                                        )\n"
    "                                        _c1,_c2,_c3 = st.columns(3)\n"
    "                                        _c1.metric(\"SKUs\",     _summ[\"total\"])\n"
    "                                        _c2.metric(\"Critical\", _summ[\"critical\"])\n"
    "                                        _c3.metric(\"Health\",   f\"{_summ['health_score']}%\")\n"
    "                                        st.rerun()\n"
    "                with _col_disc:\n"
    "                    if st.button(\"Disconnect\", key=f\"disc_{t_id}\",\n"
    "                                  type=\"secondary\"):\n"
    "                        _sc.disconnect_store_sheet(t_id)\n"
    "                        st.rerun()\n"
    "            else:\n"
    "                st.info(\n"
    "                    \"Once connected, your agent syncs this sheet automatically \"\n"
    "                    \"every 30 min. You can still upload files manually below.\"\n"
    "                )\n"
    "                _sa_email = _sc.get_service_account_email() if _SHEETS_ENABLED else None\n"
    "                if _sa_email:\n"
    "                    st.caption(\n"
    "                        f\"1️⃣  Share your Google Sheet with: `{_sa_email}`  \"\n"
    "                        f\"(view-only is fine)\"\n"
    "                    )\n"
    "                    st.caption(\"2️⃣  Paste the sheet URL below and click Connect.\")\n"
    "                else:\n"
    "                    st.caption(\n"
    "                        \"Set the GOOGLE_CREDENTIALS env var (base64 service account JSON) \"\n"
    "                        \"to enable auto-sync.\"\n"
    "                    )\n"
    "                _new_url = st.text_input(\n"
    "                    \"Google Sheet URL\",\n"
    "                    placeholder=\"https://docs.google.com/spreadsheets/d/…/edit\",\n"
    "                    key=f\"sheet_url_input_{t_id}\",\n"
    "                )\n"
    "                if st.button(\"Connect sheet\", key=f\"conn_{t_id}\",\n"
    "                              type=\"primary\") and _new_url.strip():\n"
    "                    with st.spinner(\"Testing connection…\"):\n"
    "                        _test = _sc.pull_sheet(_new_url.strip())\n"
    "                    if _test is not None and not _test.empty:\n"
    "                        _sc.save_store_sheet(t_id, _new_url.strip())\n"
    "                        st.success(\n"
    "                            f\"✅ Connected! Found {len(_test)} rows. \"\n"
    "                            \"Agent will auto-sync every 30 min.\"\n"
    "                        )\n"
    "                        st.rerun()\n"
    "                    else:\n"
    "                        st.error(\n"
    "                            \"Could not read the sheet. Make sure you shared it \"\n"
    "                            \"with the service account email above, then try again.\"\n"
    "                        )\n"
    "\n"
    "        st.markdown(\"---\")\n"
    "        st.markdown(\"##### 📤 Manual upload (always available as fallback)\")\n"
    "\n"
    "        with st.expander(\"Expected column format\"):"
)

if "Google Sheets auto-sync" not in src:
    if anchor in src:
        src = src.replace(anchor, sheets_ui)
        print("   app.py: inserted Google Sheets section into upload tab")
    else:
        print("   ERROR: upload tab anchor not found — check app.py manually")
        sys.exit(1)
else:
    print("   app.py: Sheets section already present (skip)")

write("app.py", src)

# ── 3. Add helper functions to sheets_connector.py ───────────────
sc = read("sheets_connector.py")

if "def disconnect_store_sheet" not in sc:
    sc = sc.rstrip() + '''


def disconnect_store_sheet(store_id: str) -> bool:
    """Remove a store\'s Google Sheet connection."""
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
'''
    write("sheets_connector.py", sc)
    print("   sheets_connector.py: added disconnect + get_service_account_email")
else:
    print("   sheets_connector.py: helpers already present (skip)")

# ── 4. Compile checks ─────────────────────────────────────────────
import py_compile, traceback
all_ok = True
for f in ["app.py", "sheets_connector.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print(f"   OK  {f}")
    except py_compile.PyCompileError as e:
        print(f"   FAIL {f}: {e}")
        all_ok = False

print()
if all_ok:
    print("✅ Done — both options now live in the Upload tab.")
else:
    print("⚠️  Compile error — restore from _pre_fix_backup/ and check output above.")