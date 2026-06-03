"""
patch_premium_ui.py
────────────────────────────────────────────────────────────────
Applies four improvements:

  1. Self-signup  — any phone can log in; first-timers get an
                    onboarding screen to create their business.
                    No more hardcoded / pre-seeded users needed.
  2. Favicon      — uses assets/dishii-logo.png (falls back to 🍽️)
  3. Stores UI    — premium redesign: single-manager create form,
                    cleaner store cards, expandable manager list.
  4. SQL file     — removes the demo seed data (run separately).

Run from /workspaces/dishii:
    python3 patch_premium_ui.py
"""
import io, sys

def read(p):  return io.open(p, encoding="utf-8").read()
def write(p, s): io.open(p, "w", encoding="utf-8").write(s); print(f"   patched {p}")

# ══════════════════════════════════════════════════════════════
# 1.  auth.py  ─ self-signup + onboarding
# ══════════════════════════════════════════════════════════════
auth_src = read("auth.py")

# 1a. Remove the registration gate from send_otp so any phone gets a code
old_gate = (
    '    # Check if this phone belongs to any manager or admin\n'
    '    db = _db()\n'
    '    mgr = db.table("store_managers").select("id,name,store_id").eq("phone", clean).eq("is_active", True).execute()\n'
    '    adm = db.table("admin_accounts").select("id,name").eq("phone", clean).eq("is_active", True).execute()\n'
    '\n'
    '    if not mgr.data and not adm.data:\n'
    '        return False, "Phone not registered. Contact your store admin."\n'
    '\n'
    '    # Invalidate old OTPs'
)
new_gate = '    # Invalidate old OTPs'

if old_gate in auth_src:
    auth_src = auth_src.replace(old_gate, new_gate)
    print("   auth.py: removed registration gate from send_otp")
else:
    print("   auth.py: send_otp gate already removed (skip)")

# 1b. In verify_otp, return "new_user" instead of "Manager not found"
old_notfound = (
    '    if not mgrs.data:\n'
    '        return False, "Manager not found."'
)
new_notfound = (
    '    if not mgrs.data:\n'
    '        # First-time user — flag for onboarding\n'
    '        st.session_state["_new_user_phone"] = clean\n'
    '        return True, "new_user"'
)
if old_notfound in auth_src:
    auth_src = auth_src.replace(old_notfound, new_notfound)
    print("   auth.py: verify_otp now routes new users to onboarding")
else:
    print("   auth.py: new_user route already present (skip)")

# 1c. Add render_onboarding() before render_store_picker
onboarding_fn = '''
def render_onboarding():
    """
    First-time setup screen shown when a phone number isn't
    registered yet. Creates the store + manager record and logs
    the user in automatically.
    """
    import db as _db_mod, re as _re
    phone = st.session_state.get("_new_user_phone", "")

    st.markdown("""
    <style>
    .main .block-container{max-width:520px;margin:0 auto;padding-top:5rem;}
    [data-testid="stSidebar"]{display:none;}
    </style>""", unsafe_allow_html=True)

    st.markdown("## Welcome to Dishii 👋")
    st.caption("Set up your business in 30 seconds — no credit card needed.")
    st.markdown("")

    with st.form("onboarding_form"):
        st.markdown("**Your name**")
        owner_name = st.text_input("Name", placeholder="e.g. Jane Mwangi",
                                   label_visibility="collapsed")

        st.markdown("**Business name**")
        biz_name = st.text_input("Business", placeholder="e.g. Quikmart Westlands",
                                 label_visibility="collapsed")

        col_l, col_t = st.columns(2)
        with col_l:
            st.markdown("**Location**")
            location = st.text_input("Location", placeholder="Westlands, Nairobi",
                                     label_visibility="collapsed")
        with col_t:
            st.markdown("**Business type**")
            biz_type = st.selectbox("Type",
                ["supermarket", "mini_mart", "restaurant",
                 "distributor", "pharmacy", "wholesale"],
                label_visibility="collapsed")

        submitted = st.form_submit_button("Get Started →", type="primary",
                                          use_container_width=True)

    if submitted:
        if not owner_name.strip() or not biz_name.strip():
            st.error("Please enter your name and business name.")
            return

        try:
            store = _db_mod.create_store(biz_name.strip(), location.strip(), biz_type)
            if not store:
                st.error("Could not create store — please try again.")
                return
            _db_mod.add_manager(store["id"], owner_name.strip(), phone, "owner")

            # Log the user in directly
            st.session_state[SESSION_KEY]  = True
            st.session_state[IS_ADMIN_KEY] = False
            st.session_state[MANAGER_KEY]  = {
                "name": owner_name.strip(), "role": "owner", "phone": phone
            }
            st.session_state["_mgr_stores"] = [{"store_id": store["id"], "role": "owner"}]
            st.session_state[STORE_KEY] = store
            st.session_state.pop("_new_user_phone", None)
            st.success(f"✅ {biz_name} is live! Welcome to Dishii.")
            st.rerun()
        except Exception as e:
            st.error(f"Setup failed: {e}")

    st.markdown("")
    if st.button("← Use a different number"):
        st.session_state.pop("_new_user_phone", None)
        logout()
        st.rerun()

'''

if "def render_onboarding" not in auth_src:
    auth_src = auth_src.replace("def render_store_picker():", onboarding_fn + "def render_store_picker():")
    print("   auth.py: added render_onboarding()")
else:
    print("   auth.py: render_onboarding already present (skip)")

write("auth.py", auth_src)


# ══════════════════════════════════════════════════════════════
# 2.  app.py  ─ favicon + onboarding gate + premium stores UI
# ══════════════════════════════════════════════════════════════
app_src = read("app.py")

# 2a. Favicon
old_icon = 'page_icon="🍔"'
new_icon = ('page_icon=(__import__("PIL.Image",fromlist=["Image"]).Image.open("assets/dishii-logo.png")\n'
            '           if __import__("os").path.exists("assets/dishii-logo.png") else "🍽️")')
if old_icon in app_src:
    app_src = app_src.replace(old_icon, new_icon)
    print("   app.py: favicon updated to use logo")
else:
    print("   app.py: favicon already updated (skip)")

# 2b. Onboarding gate (insert between existing two gates)
old_gates = (
    'if not auth.is_logged_in():\n'
    '    auth.render_login_page()\n'
    '    st.stop()\n'
    'if (not auth.is_admin() and auth.get_current_store() is None'
)
new_gates = (
    'if not auth.is_logged_in():\n'
    '    auth.render_login_page()\n'
    '    st.stop()\n'
    'if st.session_state.get("_new_user_phone"):\n'
    '    auth.render_onboarding()\n'
    '    st.stop()\n'
    'if (not auth.is_admin() and auth.get_current_store() is None'
)
if "_new_user_phone" not in app_src:
    app_src = app_src.replace(old_gates, new_gates)
    print("   app.py: added onboarding gate")
else:
    print("   app.py: onboarding gate already present (skip)")

# 2c. Premium Stores & Managers UI
old_stores = read("app.py")  # re-read to get latest (not needed, use app_src)

STORES_OLD = '''with t_stores:
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
                f\'<div class="icard" style="border-left-color:{bc};">\' 
                f\'<div style="display:flex;justify-content:space-between;">\' 
                f\'<div class="icard-title">{"✓ " if is_sel else ""}{s["name"]}</div>\' 
                f\'<div style="font-size:0.65rem;color:{"#10b981" if has_inv else "#475569"}.">{"Inventory loaded" if has_inv else "No inventory"}</div></div>\' 
                f\'<div class="icard-reason">{s.get("location","—")} &middot; {s.get("store_type","—")}</div>\' 
                f\'<div class="icard-meta">{mgr_txt}</div>\' 
                f\'</div>\', unsafe_allow_html=True)

            # List managers with remove buttons
            ml2 = cached_managers(s["id"])
            if ml2:
                with st.expander(f"Managers ({len(ml2)}) — {s[\'name\']}"):
                    for m in ml2:
                        c1, c2 = st.columns([5,1])
                        with c1:
                            st.markdown(f"**{m[\'name\']}** · {m.get(\'role\',\'manager\').title()} · +{m[\'phone\']}")
                        with c2:
                            if st.button("✕", key=f"rm_{m[\'id\']}", help=f"Remove {m[\'name\']}"):
                                db.get_db().table("store_managers").update({"is_active": False}).eq("id", m["id"]).execute()
                                st.success(f"Removed {m[\'name\']}")
                                st.cache_data.clear()
                                st.rerun()

            # Add manager to existing store
            with st.expander(f"Add manager to {s[\'name\']}"):
                with st.form(f"add_mgr_{s[\'id\']}"):
                    ac1,ac2,ac3 = st.columns(3)
                    with ac1: am_n = st.text_input("Name *",  key=f"amn_{s[\'id\']}")
                    with ac2: am_p = st.text_input("Phone *", key=f"amp_{s[\'id\']}", placeholder="+254... or +1... or +44...")
                    with ac3: am_r = st.selectbox("Role", ["manager","owner","supervisor"], key=f"amr_{s[\'id\']}")
                    if st.form_submit_button("Add Manager", type="primary"):
                        if am_n.strip() and am_p.strip():
                            db.add_manager(s["id"], am_n.strip(), am_p.strip(), am_r)
                            clean = am_p.replace("+","").replace(" ","").replace("-","")
                            wa.send(clean, wa.msg_welcome(s["name"], am_n.strip()))
                            st.success(f"{am_n} added as {am_r}. Welcome message sent.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Name and phone required")'''

STORES_NEW = '''with t_stores:
    st.markdown("""<style>
    .sm-card{background:#0d1b2e;border:1px solid #1a2f4a;border-radius:14px;
             padding:1.25rem 1.5rem;margin-bottom:1rem;transition:border-color .2s;}
    .sm-card.active{border-left:3px solid #10b981;}
    .sm-name{font-size:1rem;font-weight:600;color:#f1f5f9;margin-bottom:0.2rem;}
    .sm-meta{font-size:0.75rem;color:#64748b;margin-bottom:0.75rem;}
    .sm-chip{display:inline-flex;align-items:center;gap:5px;background:#1e293b;
             border-radius:20px;padding:3px 10px;font-size:0.72rem;color:#94a3b8;
             margin:2px;}
    .sm-role{font-size:0.6rem;background:#1e3a5f;color:#60a5fa;
             padding:1px 6px;border-radius:8px;font-weight:500;}
    .sm-badge-live{font-size:0.65rem;background:#064e3b;color:#10b981;
                   padding:2px 8px;border-radius:12px;}
    .sm-badge-empty{font-size:0.65rem;background:#1e293b;color:#64748b;
                    padding:2px 8px;border-radius:12px;}
    </style>""", unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────
    st.markdown("### Stores & Managers")
    st.caption("Each store is fully isolated. Managers log in with their phone — no passwords needed.")
    st.markdown("")

    # ── Create new store ──────────────────────────────────────
    _all_s = _allowed_stores()
    with st.expander("➕  Add a new store", expanded=len(_all_s) == 0):
        with st.form("new_store_form", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1: s_name = st.text_input("Store name *", placeholder="Quikmart Westlands")
            with c2: s_loc  = st.text_input("Location",     placeholder="Nairobi")
            with c3: s_type = st.selectbox("Type",
                ["supermarket","mini_mart","restaurant","distributor","pharmacy","wholesale"])

            st.markdown("---")
            st.markdown("**First manager** — you can add more after creating")
            m1, m2, m3 = st.columns([2, 2, 1])
            with m1: mn = st.text_input("Full name *",       key="ns_mn1", placeholder="e.g. Jane Mwangi")
            with m2: mp = st.text_input("WhatsApp number *", key="ns_mp1", placeholder="+254 720 521 291")
            with m3: mr = st.selectbox("Role", ["owner","manager","supervisor"], key="ns_mr1")

            if st.form_submit_button("Create Store", type="primary", use_container_width=True):
                if not s_name.strip():
                    st.error("Store name is required.")
                elif not mn.strip() or not mp.strip():
                    st.error("Add a name and phone for the first manager.")
                else:
                    try:
                        new_store = db.create_store(s_name.strip(), s_loc.strip(), s_type)
                        if new_store:
                            db.add_manager(new_store["id"], mn.strip(), mp.strip(), mr)
                            clean_p = mp.replace("+","").replace(" ","").replace("-","")
                            wa.send(clean_p, wa.msg_welcome(s_name.strip(), mn.strip()))
                            st.success(f"✅ **{s_name}** is live. Welcome message sent to {mn}.")
                            st.session_state["active_store"] = new_store["id"]
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Could not create store. Try again.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    st.markdown("")

    # ── Existing stores ───────────────────────────────────────
    if not _all_s:
        st.info("No stores yet — create your first one above.")
    else:
        for s in _all_s:
            ml      = cached_managers(s["id"])
            is_sel  = s["id"] == selected_id
            has_inv = len(cached_inventory(s["id"])) > 0
            mgr_chips = "".join([
                f\'<span class="sm-chip">\' +
                (m.get("name","?")[:16]) +
                f\' <span class="sm-role">{m.get("role","mgr")}</span></span>\'
                for m in ml
            ]) or \'<span style="color:#475569;font-size:0.75rem;">No managers yet</span>\'

            badge = ('<span class="sm-badge-live">● Inventory loaded</span>'
                     if has_inv else
                     '<span class="sm-badge-empty">No inventory</span>')
            _card_cls = "sm-card active" if is_sel else "sm-card"
            _tick     = "✓ " if is_sel else ""

            st.markdown(
                f'<div class="{_card_cls}">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<div class="sm-name">{_tick}{s["name"]}</div>{badge}</div>'
                f'<div class="sm-meta">{s.get("location","—")} · {s.get("store_type","—")}</div>'
                f'<div>{mgr_chips}</div></div>',
                unsafe_allow_html=True)

            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                with st.expander(f"👥 Managers ({len(ml)})"):
                    for m in ml:
                        rc1, rc2 = st.columns([5, 1])
                        with rc1:
                            st.markdown(
                                f"**{m['name']}** &nbsp;·&nbsp; "
                                f"{m.get('role','manager').title()} &nbsp;·&nbsp; "
                                f"`+{m['phone']}`"
                            )
                        with rc2:
                            if st.button("Remove", key=f"rm_{m['id']}", type="secondary"):
                                db.get_db().table("store_managers") \\
                                    .update({"is_active": False}).eq("id", m["id"]).execute()
                                st.cache_data.clear()
                                st.rerun()
            with col_exp2:
                with st.expander("➕ Add manager"):
                    with st.form(f"add_mgr_{s['id']}"):
                        f1, f2, f3 = st.columns([2, 2, 1])
                        with f1: am_n = st.text_input("Name *",   key=f"amn_{s['id']}", placeholder="Full name")
                        with f2: am_p = st.text_input("Phone *",  key=f"amp_{s['id']}", placeholder="+254 7XX")
                        with f3: am_r = st.selectbox("Role", ["manager","owner","supervisor"],
                                                      key=f"amr_{s['id']}")
                        if st.form_submit_button("Add", type="primary", use_container_width=True):
                            if am_n.strip() and am_p.strip():
                                db.add_manager(s["id"], am_n.strip(), am_p.strip(), am_r)
                                clean_ap = am_p.replace("+","").replace(" ","").replace("-","")
                                wa.send(clean_ap, wa.msg_welcome(s["name"], am_n.strip()))
                                st.success(f"✅ {am_n} added.")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Name and phone required.")
            st.markdown("")'''

if 'st.markdown("#### Create New Store")' in app_src:
    # Find and replace the whole block
    start = app_src.find("with t_stores:")
    end   = app_src.find("\n# ══", start)
    if start != -1 and end != -1:
        app_src = app_src[:start] + STORES_NEW + "\n" + app_src[end:]
        print("   app.py: Stores & Managers UI redesigned")
    else:
        print("   app.py: stores block end not found — skipping UI redesign")
else:
    print("   app.py: stores UI already redesigned (skip)")

write("app.py", app_src)

# ══════════════════════════════════════════════════════════════
# 3.  Compile checks
# ══════════════════════════════════════════════════════════════
import py_compile
ok = True
for f in ["auth.py", "app.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print(f"   OK  {f}")
    except py_compile.PyCompileError as e:
        print(f"   FAIL {f}: {e}")
        ok = False

print()
if ok:
    print("✅  All done. Run:\n    python3 -m streamlit run app.py")
else:
    print("⚠️  Fix compile errors above before running.")