"""
auth.py — Dishii Authentication
Phone + WhatsApp OTP login. No passwords.
Session stored in st.session_state.
"""
import os
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Session keys ──────────────────────────────────────────────
SESSION_KEY     = "dishii_session"
STORE_KEY       = "dishii_store"
MANAGER_KEY     = "dishii_manager"
IS_ADMIN_KEY    = "dishii_is_admin"
OTP_PHONE_KEY   = "dishii_otp_phone"
OTP_SENT_KEY    = "dishii_otp_sent"
OTP_MSG_KEY     = "dishii_otp_msg"


def _db():
    from supabase import create_client
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# ── OTP ───────────────────────────────────────────────────────

def generate_otp() -> str:
    return str(random.randint(100000, 999999))


def _normalize_phone(phone: str) -> str:
    """Accept any common format → digits only with country code.
    0720521291 → 254720521291
    +254720521291 → 254720521291
    254720521291 → 254720521291
    """
    p = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
    if p.startswith("0") and len(p) == 10:   # local Kenyan format
        p = "254" + p[1:]
    return p

def send_otp(phone: str) -> Tuple[bool, str]:
    """
    Generate OTP, store in DB, send via WhatsApp.
    Returns (success, message).
    """
    # Re-read .env every call so DISHII_DEV_MODE works without restart
    load_dotenv(override=True)

    # Normalize phone — accept any common format:
    # 0720521291 → 254720521291
    # +254720521291 → 254720521291
    # 254720521291 → 254720521291
    # 0720 521 291 → 254720521291
    clean = phone.strip().replace("+","").replace(" ","").replace("-","")
    if clean.startswith("0") and 9 <= len(clean) <= 10:
        clean = "254" + clean[1:]
    if not clean.isdigit() or len(clean) < 9:
        return False, "Invalid phone number. Use format: 254720521291"

    # Invalidate old OTPs
    db.table("auth_otp").update({"used": True}).eq("phone", clean).eq("used", False).execute()

    # Generate new OTP
    code = generate_otp()
    expires = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    db.table("auth_otp").insert({
        "phone":      clean,
        "otp_code":   code,
        "expires_at": expires,
        "used":       False
    }).execute()

    # Send via WhatsApp
    msg = (
        f"🔐 *Dishii Login Code*\n\n"
        f"Your verification code: *{code}*\n\n"
        f"Valid for 5 minutes.\n"
        f"Do not share this code with anyone."
    )
    try:
        import whatsapp as wa
        sent = wa.send(clean, msg)
        if sent:
            logger.info(f"OTP sent to {clean}")
            return True, "Code sent to your WhatsApp"
        else:
            logger.warning(f"WhatsApp unavailable, OTP: {code}")
            if os.getenv("DISHII_DEV_MODE") == "1":
                return True, f"__devcode__{code}"
            return False, "Could not send the code. Check WhatsApp is connected in Evolution API."
    except Exception as e:
        logger.error(f"OTP send error: {e}")
        if os.getenv("DISHII_DEV_MODE") == "1":
            return True, f"__devcode__{code}"
        return False, f"WhatsApp error: {e}"

def verify_otp(phone: str, code: str) -> Tuple[bool, str]:
    """
    Verify OTP. Returns (success, message).
    On success, session is set in st.session_state.
    """
    clean = phone.strip().replace("+","").replace(" ","").replace("-","")
    if clean.startswith("0") and 9 <= len(clean) <= 10:
        clean = "254" + clean[1:]
    code  = code.strip()
    db    = _db()

    # Find valid OTP
    r = db.table("auth_otp").select("*").eq("phone", clean).eq("otp_code", code).eq("used", False).execute()

    if not r.data:
        return False, "Invalid code. Try again or request a new one."

    otp = r.data[0]

    # Check expiry
    expires = datetime.fromisoformat(otp["expires_at"].replace("Z","+00:00"))
    from datetime import timezone
    if datetime.now(timezone.utc) > expires:
        return False, "Code expired. Request a new one."

    # Mark OTP used
    db.table("auth_otp").update({"used": True}).eq("id", otp["id"]).execute()

    # Check if admin
    adm = db.table("admin_accounts").select("*").eq("phone", clean).eq("is_active", True).execute()
    if adm.data:
        st.session_state[SESSION_KEY]  = True
        st.session_state[IS_ADMIN_KEY] = True
        st.session_state[MANAGER_KEY]  = {"name": adm.data[0]["name"], "role": "admin", "phone": clean}
        st.session_state[STORE_KEY]    = None  # admin picks any store
        return True, "admin"

    # Get manager's stores
    mgrs = db.table("store_managers").select("*").eq("phone", clean).eq("is_active", True).execute()
    if not mgrs.data:
        # First-time user — flag for onboarding
        st.session_state["_new_user_phone"] = clean
        return True, "new_user"

    st.session_state[SESSION_KEY]  = True
    st.session_state[IS_ADMIN_KEY] = False
    st.session_state[MANAGER_KEY]  = mgrs.data[0]
    st.session_state["_mgr_stores"] = mgrs.data  # all stores this manager belongs to

    # If only one store, set it directly
    if len(mgrs.data) == 1:
        store = db.table("stores").select("*").eq("id", mgrs.data[0]["store_id"]).single().execute()
        st.session_state[STORE_KEY] = store.data
        return True, "single_store"
    else:
        st.session_state[STORE_KEY] = None
        return True, "multi_store"


# ── Session helpers ───────────────────────────────────────────

def is_logged_in() -> bool:
    return st.session_state.get(SESSION_KEY, False)

def is_admin() -> bool:
    return st.session_state.get(IS_ADMIN_KEY, False)

def get_current_manager() -> Optional[Dict]:
    return st.session_state.get(MANAGER_KEY)

def get_current_store() -> Optional[Dict]:
    return st.session_state.get(STORE_KEY)

def get_current_store_id() -> Optional[str]:
    store = get_current_store()
    return store["id"] if store else None

def set_current_store(store: Dict):
    st.session_state[STORE_KEY] = store

def logout():
    for key in [SESSION_KEY, STORE_KEY, MANAGER_KEY, IS_ADMIN_KEY,
                OTP_PHONE_KEY, OTP_SENT_KEY, "_mgr_stores"]:
        st.session_state.pop(key, None)

def get_manager_stores() -> List[Dict]:
    """Get all stores for the current manager."""
    mgr_stores = st.session_state.get("_mgr_stores", [])
    if not mgr_stores:
        return []
    db = _db()
    store_ids = [m["store_id"] for m in mgr_stores]
    result = []
    for sid in store_ids:
        try:
            r = db.table("stores").select("*").eq("id", sid).single().execute()
            if r.data:
                # Attach role for this store
                role = next((m["role"] for m in mgr_stores if m["store_id"] == sid), "manager")
                r.data["_role"] = role
                result.append(r.data)
        except Exception:
            pass
    return result


# ── Login UI ──────────────────────────────────────────────────

def render_login_page():
    """
    Renders the login page. Clean, minimal, professional.
    Called when user is not authenticated.
    """
    # Load logo
    import base64
    logo_b64 = ""
    for p in ["assets/dishii-logo.png", "dishii-logo.png"]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                logo_b64 = base64.b64encode(f.read()).decode()
            break

    st.markdown("""
    <style>
    .main .block-container{
        max-width: 420px;
        margin: 0 auto;
        padding-top: 6rem;
    }
    [data-testid="stSidebar"]{display:none;}
    footer{visibility:hidden;}
    #MainMenu{visibility:hidden;}

    .login-logo{text-align:center;margin-bottom:2rem;}
    .login-title{
        font-size:1.6rem;font-weight:700;color:#f1f5f9;
        text-align:center;margin-bottom:0.25rem;
    }
    .login-sub{
        font-size:0.85rem;color:#64748b;
        text-align:center;margin-bottom:2.5rem;
    }
    .login-card{
        background:#0d1b2e;border:1px solid #1a2f4a;
        border-radius:16px;padding:2rem;
    }
    .login-divider{
        text-align:center;color:#475569;
        font-size:0.75rem;margin:1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

    # Logo + title
    if logo_b64:
        st.markdown(
            f'<div class="login-logo">'
            f'<img src="data:image/png;base64,{logo_b64}" width="60" style="border-radius:14px;">'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div class="login-title">Dishii</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">Food Operations Intelligence</div>', unsafe_allow_html=True)

    otp_sent  = st.session_state.get(OTP_SENT_KEY, False)
    otp_phone = st.session_state.get(OTP_PHONE_KEY, "")

    if not otp_sent:
        # ── Step 1: Enter phone ───────────────────────────────
        with st.container():
            st.markdown('<div class="login-card">', unsafe_allow_html=True)
            st.markdown("**Enter your phone number**")
            st.caption("We'll send a verification code to your WhatsApp")

            phone = st.text_input(
                "Phone",
                placeholder="+254 720 521 291  or  +1 212 555 1234",
                label_visibility="collapsed",
                key="login_phone_input"
            )

            if st.button("Send Code", type="primary", use_container_width=True):
                if not phone.strip():
                    st.error("Enter your phone number")
                else:
                    with st.spinner("Sending code..."):
                        ok, msg = send_otp(phone.strip())
                    if ok:
                        st.session_state[OTP_PHONE_KEY] = phone.strip()
                        st.session_state[OTP_SENT_KEY]  = True
                        st.session_state[OTP_MSG_KEY]   = msg
                        st.rerun()
                    else:
                        st.error(msg)

            st.markdown('</div>', unsafe_allow_html=True)

    else:
        # ── Step 2: Enter OTP ─────────────────────────────────
        with st.container():
            st.markdown('<div class="login-card">', unsafe_allow_html=True)

            masked = otp_phone[:4] + "••••" + otp_phone[-3:] if len(otp_phone) > 7 else otp_phone
            st.markdown(f"**Enter the code sent to {masked}**")
            otp_msg = st.session_state.get(OTP_MSG_KEY, "")
            if otp_msg and otp_msg.startswith("__devcode__"):
                dev_code = otp_msg.replace("__devcode__","").strip()
                st.warning(f"⚠️ WhatsApp not connected. Your code: **{dev_code}**")
            elif otp_msg:
                st.success(otp_msg)
            else:
                st.caption("Check your WhatsApp — valid for 5 minutes")

            code = st.text_input(
                "Code",
                placeholder="6-digit code",
                max_chars=6,
                label_visibility="collapsed",
                key="login_otp_input"
            )

            if st.button("Verify & Login", type="primary", use_container_width=True):
                if not code.strip():
                    st.error("Enter the verification code")
                else:
                    with st.spinner("Verifying..."):
                        ok, result = verify_otp(otp_phone, code.strip())
                    if ok:
                        st.session_state.pop(OTP_SENT_KEY, None)
                        st.session_state.pop(OTP_PHONE_KEY, None)
                        st.rerun()
                    else:
                        st.error(result)

            st.markdown('<div class="login-divider">─────────────────</div>', unsafe_allow_html=True)

            if st.button("← Change number", use_container_width=True):
                st.session_state.pop(OTP_SENT_KEY, None)
                st.session_state.pop(OTP_PHONE_KEY, None)
                st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)



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

def render_store_picker():
    """
    Shown after login when manager has multiple stores.
    Clean store selection UI.
    """
    mgr   = get_current_manager()
    name  = mgr.get("name","") if mgr else ""
    stores = get_manager_stores()

    st.markdown("""
    <style>
    .main .block-container{max-width:500px;margin:0 auto;padding-top:5rem;}
    [data-testid="stSidebar"]{display:none;}
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"### Welcome, {name}")
    st.markdown("**Select the store you want to manage:**")
    st.markdown("")

    for store in stores:
        role = store.get("_role","manager")
        col1, col2 = st.columns([4,1])
        with col1:
            st.markdown(
                f'<div style="background:#0d1b2e;border:1px solid #1a2f4a;border-radius:12px;'
                f'padding:1rem 1.25rem;margin-bottom:0.5rem;">'
                f'<div style="font-size:0.9rem;font-weight:600;color:#f1f5f9;">{store["name"]}</div>'
                f'<div style="font-size:0.7rem;color:#64748b;margin-top:0.2rem;">'
                f'{store.get("location","—")} &middot; {store.get("store_type","—")} &middot; {role.title()}'
                f'</div></div>', unsafe_allow_html=True)
        with col2:
            st.markdown("<div style='margin-top:0.75rem;'>", unsafe_allow_html=True)
            if st.button("Enter", key=f"pick_{store['id']}", type="primary"):
                set_current_store(store)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("")
    if st.button("Logout", use_container_width=False):
        logout()
        st.rerun()


def render_sidebar_user(selected_store_id: str = None):
    """
    Renders user info in sidebar — name, role, store, logout button.
    Call this inside the sidebar block.
    """
    mgr   = get_current_manager()
    store = get_current_store()
    if not mgr:
        return

    role_colors = {"owner":"#10b981","manager":"#3b82f6","supervisor":"#f59e0b","admin":"#8b5cf6"}
    role        = mgr.get("role","manager")
    role_color  = role_colors.get(role,"#64748b")
    name        = mgr.get("name","User")

    st.markdown(
        f'<div style="background:#0d1b2e;border:1px solid #1a2f4a;border-radius:10px;'
        f'padding:0.75rem 1rem;margin-bottom:0.75rem;">'
        f'<div style="font-size:0.85rem;font-weight:600;color:#f1f5f9;">{name}</div>'
        f'<div style="font-size:0.65rem;margin-top:0.2rem;">'
        f'<span style="color:{role_color};font-weight:500;">{role.title()}</span>'
        + (f'<span style="color:#475569;"> &middot; {store["name"]}</span>' if store else "")
        + f'</div></div>', unsafe_allow_html=True)

    # Store switcher for multi-store managers
    mgr_stores = get_manager_stores()
    if len(mgr_stores) > 1 and not is_admin():
        with st.expander("Switch store"):
            for s in mgr_stores:
                is_current = store and s["id"] == store.get("id")
                if st.button(
                    f"{'✓ ' if is_current else ''}{s['name']}",
                    key=f"sw_{s['id']}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary"
                ):
                    set_current_store(s)
                    st.rerun()

    if st.button("Sign out", use_container_width=True):
        logout()
        st.rerun()