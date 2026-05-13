import streamlit as st
import pandas as pd
import jira_utils
import jira_config
import os
import logging
import json
import time
from datetime import datetime, timedelta
import yaml
import importlib
from yaml.loader import SafeLoader
from supabase import create_client, Client
import time
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import re

# Encryption Setup
ENCRYPTION_KEY = st.secrets.get("ENCRYPTION_KEY")
cipher_suite = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

def encrypt_data(data):
    if not cipher_suite or not data:
        return data
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data):
    if not cipher_suite or not encrypted_data:
        return encrypted_data
    try:
        return cipher_suite.decrypt(encrypted_data.encode()).decode()
    except Exception:
        # Fallback for old plaintext data (Phase 1 backward compatibility)
        return encrypted_data

# Supabase Config (These should ideally be in secrets/config)
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

# Initialize Supabase client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")

# UI Constants
PAGE_TITLE = "Jira Version Manager"
st.set_page_config(page_title=PAGE_TITLE, layout="wide", initial_sidebar_state="expanded")

def get_user_projects_file(username):
    return f"{username}_managed_projects.json"

def get_user_shortcuts_file(username):
    return f"{username}_local_shortcuts.json"

def cleanup_old_logs(log_file="jira_automation_runs.log", days=30):
    if not os.path.exists(log_file):
        return
    
    cutoff = datetime.now() - timedelta(days=days)
    new_logs = []
    
    try:
        with open(log_file, "r") as f:
            for line in f:
                try:
                    log_date_str = line.split(" [")[0]
                    log_date = datetime.strptime(log_date_str, "%Y-%m-%d %H:%M:%S")
                    if log_date >= cutoff:
                        new_logs.append(line)
                except (ValueError, IndexError):
                    new_logs.append(line)
        
        with open(log_file, "w") as f:
            f.writelines(new_logs)
            
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

def sanitize_data(data):
    """Redact sensitive info from logs/errors."""
    if isinstance(data, dict):
        redacted = data.copy()
        for key in ['JIRA_API_TOKEN', 'AUTH', 'token', 'password']:
            if key in redacted:
                redacted[key] = "[REDACTED]"
        return redacted
    return data

def safe_log_error(msg, error=None):
    """Log errors without exposing sensitive config details."""
    clean_error = str(error)
    # Basic redaction for common token/email patterns in error strings
    if "@" in clean_error:
        clean_error = "[REDACTED_EMAIL_OR_CONTENT]"
    logger.error(f"{msg}: {clean_error}")

def update_jql_version(jql, old_version, new_versions):
    """
    Surgically update fixVersion in JQL.
    Handles equality (=) and membership (IN) patterns.
    new_versions is a list of strings.
    """
    if not new_versions:
        return jql
        
    # Formatting helper for new versions based on original quoting
    def format_new_list(quote_char):
        return ", ".join([f"{quote_char}{v}{quote_char}" for v in new_versions])

    # Pass 1: fixVersion = "old" or fixVersion = old
    def replace_equality(match):
        prefix = match.group(1) # fixVersion = 
        quote = match.group(2)
        if len(new_versions) > 1:
            # Change "fixVersion =" to "fixVersion in ("
            field_part = re.split(r'\s*=\s*', prefix)[0]
            in_list = format_new_list(quote)
            return f"{field_part} in ({in_list})"
        else:
            return f"{prefix}{quote}{new_versions[0]}{quote}"

    eq_pattern = rf"(?i)(fixVersion\s*=\s*)(['\"]?){re.escape(old_version)}\2"
    jql = re.sub(eq_pattern, replace_equality, jql)
    
    # Pass 2: fixVersion in (...)
    def replace_in_clause(match):
        prefix = match.group(1) # fixVersion in (
        content = match.group(2) # ... values ...
        suffix = match.group(3) # )
        
        # In the content, replace the old version
        def sub_repl(m):
            sep = m.group(1)
            quote = m.group(2)
            return f"{sep}{format_new_list(quote)}"

        sub_pattern = rf"(^|[\s,])(['\"]?){re.escape(old_version)}\2(?=$|[\s,])"
        new_content = re.sub(sub_pattern, sub_repl, content)
        return f"{prefix}{new_content}{suffix}"

    in_pattern = rf"(?i)(fixVersion\s+in\s*\()([^)]*)(\))"
    jql = re.sub(in_pattern, replace_in_clause, jql)
    
    return jql

file_handler = logging.FileHandler("jira_automation_runs.log")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(file_handler)

@st.cache_data(ttl=1800)
def load_managed_projects(username):
    if st.session_state.get("is_guest"):
        return st.session_state.get("guest_projects", [])

    if supabase:
        try:
            user_res = supabase.table("profiles").select("id").eq("username", username).single().execute()
            if user_res.data:
                user_id = user_res.data["id"]
                response = supabase.table("user_settings").select("managed_projects").eq("user_id", user_id).execute()
                if response.data:
                    return response.data[0].get("managed_projects", [])
        except Exception as e:
            logger.error(f"Supabase load error for {username}: {e}")

    filename = get_user_projects_file(username)
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading managed projects for {username}: {e}")
    return []

def save_managed_projects(username, projects):
    if st.session_state.get("is_guest"):
        st.session_state.guest_projects = projects
        st.cache_data.clear()
        return True

    if supabase:
        try:
            user_res = supabase.table("profiles").select("id").eq("username", username).single().execute()
            if user_res.data:
                user_id = user_res.data["id"]
                res = supabase.table("user_settings").upsert({
                    "user_id": user_id,
                    "managed_projects": projects
                }).execute()
                logger.info(f"Supabase save response for {username}: {res.data}")
                st.cache_data.clear()
                return True
        except Exception as e:
            logger.error(f"Supabase save error for {username}: {e}")

    filename = get_user_projects_file(username)
    try:
        with open(filename, "w") as f:
            json.dump(projects, f, indent=4)
        st.cache_data.clear()
        return True
    except Exception as e:
        logger.error(f"Error saving managed projects locally for {username}: {e}")
        return False

@st.cache_data(ttl=1800)
def load_shortcuts(username):
    if st.session_state.get("is_guest"):
        return {} # Shortcuts disabled for guests

    if supabase:
        try:
            user_res = supabase.table("profiles").select("id").eq("username", username).single().execute()
            if user_res.data:
                user_id = user_res.data["id"]
                response = supabase.table("user_settings").select("shortcuts").eq("user_id", user_id).execute()
                if response.data:
                    return response.data[0].get("shortcuts", {})
        except Exception as e:
            logger.error(f"Supabase load shortcuts error for {username}: {e}")

    filename = get_user_shortcuts_file(username)
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading shortcuts for {username}: {e}")
    return {}

def save_shortcuts(username, shortcuts):
    if st.session_state.get("is_guest"):
        return False # Shortcuts disabled for guests

    if supabase:
        try:
            user_res = supabase.table("profiles").select("id").eq("username", username).single().execute()
            if user_res.data:
                user_id = user_res.data["id"]
                res = supabase.table("user_settings").upsert({
                    "user_id": user_id,
                    "shortcuts": shortcuts
                }).execute()
                logger.info(f"Supabase save shortcuts response for {username}: {res.data}")
        except Exception as e:
            logger.error(f"Supabase save shortcuts error for {username}: {e}")

    filename = get_user_shortcuts_file(username)
    try:
        with open(filename, "w") as f:
            json.dump(shortcuts, f, indent=4)
        st.cache_data.clear()
        return True
    except Exception as e:
        logger.error(f"Error saving shortcuts locally for {username}: {e}")
        return False

def save_shortcut(username, name, projects, versions):
    shortcuts = load_shortcuts(username)
    shortcuts[name] = {"projects": projects, "versions": versions}
    return save_shortcuts(username, shortcuts)

def delete_shortcut(username, name):
    shortcuts = load_shortcuts(username)
    if name in shortcuts:
        del shortcuts[name]
        return save_shortcuts(username, shortcuts)
    return False

@st.cache_data(ttl=3600)
def get_all_jira_projects_cached(username, config_tuple):
    """Fetches ALL projects from Jira API using provided config."""
    config = dict(config_tuple)
    return jira_utils.get_projects(config)

@st.cache_data(ttl=3600)
def get_managed_projects_cached(username, config_tuple):
    """Returns only projects that are in the user's managed list."""
    all_projects = get_all_jira_projects_cached(username, config_tuple)
    managed_keys = load_managed_projects(username)
    if not all_projects:
        return []
    if managed_keys:
        projects = [p for p in all_projects if p.get('key') in managed_keys]
    else:
        # If no managed projects file, show all projects initially
        projects = all_projects
    return sorted(projects, key=lambda x: x.get('key', ''))

@st.cache_data(ttl=600)
def get_versions_cached(username, config_tuple, project_key):
    """Fetches versions for a project using provided config."""
    config = dict(config_tuple)
    return jira_utils.get_versions(config, project_key)

def get_versions_for_projects_cached(username, config_tuple, project_keys):
    """Fetches all version names for multiple projects."""
    if not project_keys:
        return []
    all_version_names = set()
    for key in project_keys:
        versions = get_versions_cached(username, config_tuple, key)
        for v in versions:
            all_version_names.add(v.get('name'))
    return sorted(list(all_version_names))

def load_jira_config(username):
    if st.session_state.get("is_guest"):
        return st.session_state.get("guest_config", {"JIRA_BASE_URL": None, "JIRA_EMAIL": None, "JIRA_API_TOKEN": None, "API_BASE": None, "AUTH": None, "HEADERS": None})

    if supabase:
        try:
            # 1. Get user_id from profiles
            user_res = supabase.table("profiles").select("id").eq("username", username).single().execute()
            if user_res.data:
                user_id = user_res.data["id"]
                # 2. Get credentials
                cred_res = supabase.table("jira_credentials").select("encrypted_token, base_url, email").eq("user_id", user_id).single().execute()
                
                if cred_res.data:
                    data = cred_res.data
                    decrypted_token = decrypt_data(data["encrypted_token"])
                    return {
                        "JIRA_BASE_URL": data["base_url"],
                        "JIRA_EMAIL": data["email"],
                        "JIRA_API_TOKEN": decrypted_token,
                        "API_BASE": f"{data['base_url']}/rest/api/3" if data['base_url'] else None,
                        "AUTH": (data["email"], decrypted_token) if data["email"] and decrypted_token else None,
                        "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
                    }
        except Exception as e:
            logger.error(f"Error loading Jira config from Supabase for {username}: {e}")
    return {"JIRA_BASE_URL": None, "JIRA_EMAIL": None, "JIRA_API_TOKEN": None, "API_BASE": None, "AUTH": None, "HEADERS": None}

def save_jira_config(username, url, email, token):
    if st.session_state.get("is_guest"):
        config_data = {
            "JIRA_BASE_URL": url,
            "JIRA_EMAIL": email,
            "JIRA_API_TOKEN": token,
            "API_BASE": f"{url}/rest/api/3" if url else None,
            "AUTH": (email, token) if email and token else None,
            "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
        }
        st.session_state.guest_config = config_data
        st.session_state.jira_config = config_data
        st.cache_data.clear()
        return True

    encrypted_token = encrypt_data(token)
    if supabase:
        try:
            # 1. Ensure user profile exists
            user_res = supabase.table("profiles").select("id").eq("username", username).execute()
            if not user_res.data:
                # If profile missing, create one (this shouldn't happen with correct flow, but safe)
                st.error("Error: User profile not found in database. Please re-login.")
                return False
            
            user_id = user_res.data[0]["id"]
                
            # 2. Upsert credentials
            supabase.table("jira_credentials").upsert({
                "user_id": user_id,
                "encrypted_token": encrypted_token,
                "base_url": url,
                "email": email
            }).execute()
            
            st.session_state.jira_config = {
                "JIRA_BASE_URL": url,
                "JIRA_EMAIL": email,
                "JIRA_API_TOKEN": token,
                "API_BASE": f"{url}/rest/api/3" if url else None,
                "AUTH": (email, token) if email and token else None,
                "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
            }
            st.cache_data.clear()
            return True
        except Exception as e:
            logger.error(f"Error saving Jira config to Supabase for {username}: {e}")
            st.error(f"Failed to save configuration to cloud: {e}")
    return False

def save_users_config(config):
    """Save user configuration locally and sync profiles to Supabase."""
    try:
        with open('users.yaml', 'w') as file:
            yaml.dump(config, file, default_flow_style=False)
    except Exception as e:
        logger.error(f"Error saving users config locally: {e}")
        return False
    
    if supabase:
        try:
            # Sync to new 'profiles' table
            usernames = config.get('credentials', {}).get('usernames', {})
            for username, user_data in usernames.items():
                # Upsert profile
                res = supabase.table("profiles").upsert({
                    "username": username,
                    "email": user_data.get("email")
                }).execute()
                logger.info(f"Supabase Profile Upsert Response: {res.data}")
        except Exception as e:
            logger.error(f"Error syncing profiles to cloud: {e}")
            return False
    return True

def render_landing_page():
    st.markdown("<h1 style='text-align: center;'>🎯 Jira Version Manager</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.2em;'>Batch manage fix versions across multiple projects with ease.</p>", unsafe_allow_html=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🚀 Features")
        st.markdown("""
        - **Batch Actions:** Create, release, archive, and rename versions across multiple projects at once.
        - **Custom Tracking:** Maintain a list of projects you care about.
        - **Quick Shortcuts:** Save your frequent project selections for one-click access.
        - **Security First:** Your API tokens are encrypted and never stored in plaintext.
        """)
        
    with col2:
        st.subheader("📖 Quick Start")
        st.markdown("""
        1. **Configure:** Enter your Jira URL, Email, and [API Token](https://id.atlassian.com/manage-profile/security/api-tokens).
        2. **Select Projects:** Add projects to your tracking list and activate them.
        3. **Perform Actions:** Create or update versions across all active projects.
        """)
        
    st.divider()
    
    cta_col1, cta_col2, cta_col3 = st.columns([1, 2, 1])
    with cta_col2:
        if st.button("🚀 Try it now (Guest Mode)", use_container_width=True, type="primary"):
            st.session_state.is_guest = True
            st.session_state.view = 'app'
            st.session_state.username = 'Guest'
            st.session_state.name = 'Guest User'
            st.session_state.authentication_status = True
            st.rerun()
            
        if st.button("🔐 Login or Sign Up", use_container_width=True):
            st.session_state.view = 'login'
            st.rerun()

    st.markdown("<p style='text-align: center; color: gray; font-size: 0.8em; margin-top: 2em;'>Note: Guest Mode data is session-only and will be cleared on refresh.</p>", unsafe_allow_html=True)

# Helper for Supabase Auth state
def get_auth_session():
    if not supabase: return None
    return supabase.auth.get_session()

def main():
    # Sync navigation state with URL query params
    params = st.query_params
    if 'page' in params:
        st.session_state.current_page = params['page']
    
    if 'view' not in st.session_state:
        st.session_state.view = 'landing'
    
    if st.session_state.view == 'landing':
        render_landing_page()
        return

    # Check for authenticated session
    session = get_auth_session()
    
    # Identify user (prioritize session state, then check session)
    user = st.session_state.get('user')
    if not user and session:
        user = session.user
    
    if not user and not st.session_state.get("is_guest"):
        # Style for centered, fixed-width input fields
        st.markdown("""
            <style>
            .auth-container {
                max-width: 400px;
                margin: 0 auto;
            }
            .stTextInput, .stButton, .stTabs {
                max-width: 400px;
                margin-left: auto !important;
                margin-right: auto !important;
            }
            .back-container {
                max-width: 400px;
                margin: 0 auto;
                text-align: right;
            }
            </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="auth-container">', unsafe_allow_html=True)
        st.markdown('<div class="back-container">', unsafe_allow_html=True)
        if st.button("⬅️ Back"):
            st.session_state.view = 'landing'
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        tab_login, tab_signup = st.tabs(["🔐 Sign In", "📝 Sign Up"])
        
        with tab_login:
            st.subheader("Welcome back")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            if st.button("Sign In", type="primary", use_container_width=True):
                try:
                    user_res = supabase.table("profiles").select("email").eq("username", username).execute()
                    if user_res.data and len(user_res.data) > 0:
                        email = user_res.data[0]["email"]
                        auth_res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state.user = auth_res.user
                        st.session_state.is_guest = False
                        st.session_state.view = 'app'
                        st.rerun()
                    else:
                        st.error("User not found.")
                except Exception as e:
                    st.error(f"Login failed: {e}")
        
        with tab_signup:
            st.subheader("Create your account")
            email = st.text_input("Email", key="signup_email")
            username = st.text_input("Username", key="signup_username")
            password = st.text_input("Password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm_password")
            
            if st.button("Sign Up", type="primary", use_container_width=True):
                if password != confirm_password:
                    st.error("Passwords do not match!")
                else:
                    try:
                        auth_res = supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"username": username}}})
                        if auth_res.user:
                            try:
                                supabase.table("profiles").insert({
                                    "id": auth_res.user.id,
                                    "username": username,
                                    "email": email
                                }).execute()
                                
                                st.balloons()
                                st.success("✅ Account created successfully!")
                                st.session_state.username = ""
                                st.session_state.email = ""
                                st.session_state.password = ""
                                st.session_state.confirm_password = ""
                                time.sleep(2)
                                st.rerun()
                            except Exception as db_e:
                                if 'profiles_username_key' in str(db_e):
                                    st.error("Registration failed: Username already taken.")
                                elif 'profiles_email_key' in str(db_e):
                                    st.error("Registration failed: Email already registered.")
                                else:
                                    st.error(f"Database error: {db_e}")
                    except Exception as e:
                        st.error(f"Registration failed: {e}")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # User is authenticated
    if user:
        # Get username from profiles table
        user_res = supabase.table("profiles").select("username").eq("id", user.id).single().execute()
        username = user_res.data["username"] if user_res.data else user.email

        st.sidebar.title(f"Welcome, {username}")
        if st.sidebar.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.is_guest = False
            st.session_state.view = 'landing'
            # Clear all sensitive session data
            if 'user' in st.session_state: del st.session_state.user
            if 'jira_config' in st.session_state: del st.session_state.jira_config
            if 'selected_projects' in st.session_state: st.session_state.selected_projects = set()
            st.rerun()
            
        # --- Initial Config Check ---
        if 'jira_config' not in st.session_state:
            st.session_state.jira_config = load_jira_config(username)
            cleanup_old_logs()
            
        is_config_valid = all([
            st.session_state.jira_config.get("JIRA_BASE_URL"), 
            st.session_state.jira_config.get("JIRA_EMAIL"), 
            st.session_state.jira_config.get("JIRA_API_TOKEN")
        ])
    else:
        username = "Guest" # Fallback for guest mode
        st.sidebar.title("Guest Mode")
        if st.sidebar.button("🔐 Sign In / Sign Up", type="primary", use_container_width=True):
            st.session_state.is_guest = False
            st.session_state.view = 'login'
            st.rerun()

    # Ensure Jira config is loaded
    if 'jira_config' not in st.session_state or st.session_state.get('last_user') != username:
        st.session_state.jira_config = load_jira_config(username)
        cleanup_old_logs()

    config_tuple = tuple(st.session_state.jira_config.items())

    is_config_valid = all([
        st.session_state.jira_config.get("JIRA_BASE_URL"), 
        st.session_state.jira_config.get("JIRA_EMAIL"), 
        st.session_state.jira_config.get("JIRA_API_TOKEN")
    ])

    # --- Shared Data ---
    all_projects = get_managed_projects_cached(username, config_tuple) if is_config_valid else []
    project_keys = [p['key'] for p in all_projects]

    if 'selected_projects' not in st.session_state:
        st.session_state.selected_projects = set()
    
    for k in project_keys:
        if f"cb_{k}" not in st.session_state:
            st.session_state[f"cb_{k}"] = k in st.session_state.selected_projects

    if 'selected_versions' not in st.session_state:
        st.session_state.selected_versions = []

    # --- Dialogs ---
    @st.dialog("💾 Save Workspace Shortcut")
    def save_shortcut_dialog():
        if st.session_state.get("is_guest"):
            st.warning("⚠️ Shortcuts are only available for registered users. [Sign up](/?view=login) to save settings!")
            return
        current_selection = sorted(list(st.session_state.selected_projects))
        if not current_selection:
            st.warning("No projects selected to save.")
            return
        st.write(f"Save these **{len(current_selection)} projects** as a quick-access shortcut.")
        s_name = st.text_input("Shortcut Name", placeholder="e.g. Mobile Team, Project Alpha")
        if st.button("Save Shortcut", type="primary", use_container_width=True):
            if s_name:
                if save_shortcut(username, s_name, current_selection, st.session_state.selected_versions):
                    st.success(f"Saved shortcut: {s_name}")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("Please provide a name for the shortcut.")

    st.sidebar.title("🎯 Jira Manager")
    
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "📂 Manage Projects" if is_config_valid else "⚙️ Config"

    if is_config_valid:
        nav_options = ["📂 Manage Projects", "🚀 Manage Versions", "⚙️ Config"]
    else:
        nav_options = ["⚙️ Config"]
    
    if st.session_state.current_page not in nav_options:
        st.session_state.current_page = nav_options[0]

    try:
        current_index = nav_options.index(st.session_state.current_page)
    except ValueError:
        current_index = 0
    # Sync with query params
    params = st.query_params
    if 'page' in params:
        st.session_state.current_page = params['page']

    page = st.sidebar.radio("Navigation", options=nav_options, index=current_index)
    if page != st.session_state.current_page:
        st.session_state.current_page = page
        st.query_params['page'] = page
        st.rerun()

    if is_config_valid:
        st.sidebar.divider()
        col_side1, col_side2 = st.sidebar.columns([5, 2], vertical_alignment="center")
        with col_side1:
            st.markdown("<div style='display: flex; align-items: center; justify-content: center; height: 100%; margin: 0; padding: 0;'><span style='font-size: 20px; font-weight: bold; text-align: center;'>Quick Shortcuts</span></div>", unsafe_allow_html=True)
        with col_side2:
            if st.button("➕", help="Save current selection as shortcut", type="primary", use_container_width=True):
                save_shortcut_dialog()
            
        shortcuts = load_shortcuts(username)
        if not shortcuts and st.session_state.get("is_guest"):
            st.sidebar.info("💡 Sign up to save shortcuts!")
        
        for s_name, data in shortcuts.items():
            col1, col2 = st.sidebar.columns([4, 1])
            if col1.button(f"📍 {s_name}", key=f"apply_{s_name}", use_container_width=True):
                new_proj_list = data.get("projects", [])
                st.session_state.selected_projects = set(new_proj_list)
                st.session_state.selected_versions = data.get("versions", [])
                for k in project_keys:
                    st.session_state[f"cb_{k}"] = k in st.session_state.selected_projects
                st.session_state.current_page = "📂 Manage Projects"
                st.rerun()
            if col2.button("🗑️", key=f"del_{s_name}"):
                if delete_shortcut(username, s_name):
                    st.rerun()

    if page == "⚙️ Config":
        st.title("⚙️ Jira Configuration")
        # Force re-check
        current_config = st.session_state.jira_config
        valid = all([current_config.get("JIRA_BASE_URL"), current_config.get("JIRA_EMAIL"), current_config.get("JIRA_API_TOKEN")])
        if not valid:
            st.info("Update your Jira connection details here.")
        
        url = st.text_input("Jira Base URL", value=st.session_state.jira_config.get("JIRA_BASE_URL") or "", help="The URL of your Jira instance (e.g., https://yourcompany.atlassian.net)")
        # Pre-populate email with user's login email
        user_email = user.email if user else ""
        email = st.text_input("Jira Email", value=st.session_state.jira_config.get("JIRA_EMAIL") or user_email, help="The email address associated with your Jira account")
        token = st.text_input("Jira API Token", value=st.session_state.jira_config.get("JIRA_API_TOKEN") or "", type="password", help="Your personal API token. You can create one at: https://id.atlassian.com/manage-profile/security/api-tokens")
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("Save Configuration", type="primary", use_container_width=True):
                if save_jira_config(username, url, email, token):
                    st.success("✅ Configuration saved successfully!")
                    time.sleep(1)
                    st.session_state.current_page = "📂 Manage Projects"
                    st.rerun()        
        with col_btn2:
            if st.button("🔍 Test Connection", use_container_width=True):
                if not (url and email and token):
                    st.error("Please enter URL, Email, and Token to test.")
                else:
                    with st.spinner("Validating credentials..."):
                        # Prepare temporary config for testing
                        test_config = {
                            "API_BASE": f"{url}/rest/api/3",
                            "AUTH": (email, token),
                            "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
                        }
                        if jira_utils.get_user_info(test_config):
                            st.success("✅ Connection Successful! API Token is valid.")
                        else:
                            st.error("❌ Connection Failed. Please check your URL, Email, and API Token.")

    elif page == "📂 Manage Projects":
        st.title("📂 Manage Projects")
        tab1, tab2 = st.tabs(["🎯 Active workspace", "⚙️ Manage Active workspace"])

        with tab1:
            st.header("🎯 Select Active Projects")
            if not all_projects:
                st.info("💡 **Getting Started:** You haven't added any projects to your active workspace yet. Go to the **'Manage Active workspace'** tab to add some from your Jira account.")

            if all_projects:
                col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 4])
                if col_ctrl1.button("Select All", use_container_width=True):
                    st.session_state.selected_projects = set(project_keys)
                    for k in project_keys:
                        st.session_state[f"cb_{k}"] = True
                    st.rerun()
                if col_ctrl2.button("Clear Selection", use_container_width=True):
                    st.session_state.selected_projects = set()
                    for k in project_keys:
                        st.session_state[f"cb_{k}"] = False
                    st.rerun()

                cols = st.columns(4)
                for idx, p in enumerate(all_projects):
                    with cols[idx % 4]:
                        p_key = p['key']
                        def on_change(key=p_key):
                            if st.session_state.get(f"cb_{key}", False):
                                st.session_state.selected_projects.add(key)
                            else:
                                st.session_state.selected_projects.discard(key)
                        st.checkbox(f"**{p_key}**", key=f"cb_{p_key}", help=p['name'], on_change=on_change)

                if st.session_state.selected_projects:
                    st.divider()
                    if st.button("🚀 Go to: Manage Versions", use_container_width=True, type="primary"):
                        st.session_state.current_page = "🚀 Manage Versions"
                        st.query_params['page'] = "🚀 Manage Versions"
                        st.rerun()

        with tab2:
            st.subheader("➕ Add projects to Active workspace")
            all_jira_projects = get_all_jira_projects_cached(username, config_tuple)
            if all_jira_projects:
                managed_keys = set(load_managed_projects(username))
                available_to_add = [p for p in all_jira_projects if p['key'] not in managed_keys]
                if available_to_add:
                    options_add = [f"{p['key']} | {p['name']}" for p in available_to_add]
                    selected_to_add = st.multiselect("Search and select projects to add:", options=options_add, key="add_multiselect")
                    if selected_to_add:
                        if st.button("🚀 Confirm Adding Selected Projects", type="primary", use_container_width=True):
                            new_keys = [s.split(" | ")[0] for s in selected_to_add]
                            updated_managed = list(managed_keys) + new_keys
                            if save_managed_projects(username, updated_managed):
                                st.success(f"✅ Added {len(new_keys)} projects!")
                                st.cache_data.clear()
                                time.sleep(1)
                                st.rerun()
                else:
                    st.info("All your Jira projects are already in your Active workspace.")
            else:
                st.error("Could not fetch projects from Jira. Check your Config.")

            st.divider()
            if all_projects:
                st.subheader("🗑️ Remove projects from Active workspace")
                options_rm = [f"{p['key']} | {p['name']}" for p in all_projects]
                selected_to_rm = st.multiselect("Search and select projects to remove:", options=options_rm, key="rm_multiselect")
                if selected_to_rm:
                    if st.button("🗑️ Confirm Removing Selected Projects", type="primary", use_container_width=True):
                        keys_to_rm = [s.split(" | ")[0] for s in selected_to_rm]
                        managed_keys = load_managed_projects(username)
                        updated_managed = [k for k in managed_keys if k not in keys_to_rm]
                        if save_managed_projects(username, updated_managed):
                            if 'selected_projects' not in st.session_state:
                                st.session_state.selected_projects = set()
                            for k in keys_to_rm:
                                st.session_state.selected_projects.discard(k)
                            st.success(f"🗑️ Removed {len(keys_to_rm)} projects!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()

    elif page == "🚀 Manage Versions":
        st.title("🚀 Manage Versions")
        
        # Define tab labels
        tab_labels = ["🚀 Create Versions", "📦 Release/Archive", "✏️ Rename", "🔍 Update Filters"]
        
        # Determine default tab index
        default_tab_index = 0
        if st.session_state.get("active_tab") in tab_labels:
            default_tab_index = tab_labels.index(st.session_state["active_tab"])
            # Clear it so it doesn't persist forever
            del st.session_state["active_tab"]

        # If st.tabs supported index, we'd use it here. 
        # Since it doesn't in standard Streamlit, we will use a workaround:
        # We can use a radio or selectbox if we really need programmatic switching,
        # but the user requested 'tabs'. 
        # Actually, st.tabs doesn't support 'index' yet (as of May 2026 it might, 
        # but in standard 1.x it doesn't). 
        # I will check if I can use a different UI pattern or just stick to tabs.
        
        # Actually, let's stick to the current tab structure but ensure 
        # the button in Rename Tab sets the state for the Filter tab.
        
        tab_v1, tab_v2, tab_v3, tab_v4 = st.tabs(tab_labels)

        current_selection_list = sorted(list(st.session_state.selected_projects))

        with tab_v1:
            st.header("🚀 Create New Versions")
            if not current_selection_list:
                st.warning("⚠️ No projects selected. Please go to the Manage projects tab to select projects.")
            else:
                st.write(f"**Active workspace:** {', '.join(current_selection_list)}")
                new_versions_raw = st.text_input("Enter Version Names (comma separated)", placeholder="e.g. 2026Train1, 2026Train2", key="new_versions_input")
                final_versions = [v.strip() for v in new_versions_raw.split(",") if v.strip()]
                col_date1, col_date2 = st.columns(2)
                start_date = col_date1.date_input("Start Date (Optional)", value=None, key="start_date_input")
                end_date = col_date2.date_input("Release Date (Optional)", value=None, key="end_date_input")
                
                if final_versions:
                    st.divider()
                    st.session_state.selected_versions = final_versions

                    if st.button("🚀 Create Versions Across Active Projects", use_container_width=True, type="primary"):
                        start_date_str = start_date.isoformat() if start_date else None
                        end_date_str = end_date.isoformat() if end_date else None
                        for p in current_selection_list:
                            with st.status(f"Processing {p}...", expanded=True) as status:
                                existing_versions_list = get_versions_cached(username, config_tuple, p)
                                existing_names = {v["name"] for v in existing_versions_list}
                                for v in final_versions:
                                    if v in existing_names:
                                        st.info(f"{p}: {v} already exists.")
                                    else:
                                        if jira_utils.create_version(st.session_state.jira_config, p, v, start_date=start_date_str, release_date=end_date_str):
                                            st.success(f"{p}: Created {v}")
                                            st.cache_data.clear()
                                        else:
                                            st.error(f"{p}: Failed to create {v}")
                                status.update(label=f"Finished {p}", state="complete")
                        st.success("🎉 All versions created successfully across selected projects!")

        with tab_v2:
            st.header("📦 Release & Archive")
            if not current_selection_list:
                st.warning("⚠️ No projects selected. Please go to the Manage projects tab to select projects.")
            else:
                st.write(f"**Active workspace:** {', '.join(current_selection_list)}")
                show_released_only = st.checkbox("Show only Released versions (not yet archived)", key="show_released_only")
                with st.spinner("Loading versions..."):
                    all_v_details = []
                    for p in current_selection_list:
                        all_v_details.extend(jira_utils.get_versions(st.session_state.jira_config, p))
                    if show_released_only:
                        available_versions = [v['name'] for v in all_v_details if v.get("released") and not v.get("archived")]
                    else:
                        available_versions = [v['name'] for v in all_v_details if not v.get("released") and not v.get("archived")]
                    available_versions = sorted(list(set(available_versions)))
                
                target_versions = st.multiselect("Select Fix Versions", options=available_versions, key="version_multiselect_v2")
                st.session_state.selected_versions = target_versions

                if target_versions:
                    st.divider()
                    rel_col, arc_col = st.columns(2)
                    if rel_col.button("✅ Release Versions", use_container_width=True, type="primary"):
                        for p in current_selection_list:
                            with st.status(f"Releasing in {p}...", expanded=False) as status:
                                proj_versions = get_versions_cached(username, config_tuple, p)
                                for v_name in target_versions:
                                    target = next((v for v in proj_versions if v["name"] == v_name), None)
                                    if target:
                                        if target.get("released"):
                                            st.info(f"{p}: {v_name} is already released.")
                                        else:
                                            if jira_utils.release_version(st.session_state.jira_config, target["id"], p, v_name):
                                                st.success(f"{p}: Released {v_name}")
                                                st.cache_data.clear()
                                            else:
                                                st.error(f"{p}: Failed to release {v_name}")
                                    else:
                                        st.warning(f"{p}: Version {v_name} not found.")
                                status.update(label=f"Completed {p}", state="complete")
                        st.success("🎉 All selected versions released successfully!")
                    
                    if arc_col.button("📦 Archive Versions", use_container_width=True):
                        for p in current_selection_list:
                            with st.status(f"Archiving in {p}...", expanded=False) as status:
                                proj_versions = get_versions_cached(username, config_tuple, p)
                                for v_name in target_versions:
                                    target = next((v for v in proj_versions if v["name"] == v_name), None)
                                    if target:
                                        if target.get("archived"):
                                            st.info(f"{p}: {v_name} is already archived.")
                                        else:
                                            if jira_utils.archive_version(st.session_state.jira_config, target["id"], p, v_name):
                                                st.success(f"{p}: Archived {v_name}")
                                                st.cache_data.clear()
                                            else:
                                                st.error(f"{p}: Failed to archive {v_name}")
                                    else:
                                        st.warning(f"{p}: Version {v_name} not found.")
                                status.update(label=f"Completed {p}", state="complete")
                        st.success("🎉 All selected versions archived successfully!")

        with tab_v3:
            st.header("✏️ Rename Versions")
            if not current_selection_list:
                st.warning("⚠️ No projects selected. Please go to the Manage projects tab to select projects.")
            else:
                st.write(f"**Active workspace:** {', '.join(current_selection_list)}")
                
                # Initialize rename mappings in session state
                if 'rename_mappings' not in st.session_state:
                    st.session_state.rename_mappings = [{"old": None, "new": ""}]

                with st.spinner("Loading versions..."):
                    all_v_details = []
                    for p in current_selection_list:
                        all_v_details.extend(jira_utils.get_versions(st.session_state.jira_config, p))
                    available_versions = sorted(list(set([v['name'] for v in all_v_details if not v.get("archived")])))
                
                # Dynamic Mapping UX for Rename
                st.subheader("Version Renaming Mappings")
                
                def add_rename_row():
                    st.session_state.rename_mappings.append({"old": None, "new": ""})
                
                def remove_rename_row(index):
                    if len(st.session_state.rename_mappings) > 1:
                        st.session_state.rename_mappings.pop(index)

                # Header Row
                rh_col1, rh_col2, rh_col3 = st.columns([4, 4, 1])
                rh_col1.write("**Current Name**")
                rh_col2.write("**New Name**")

                for i, mapping in enumerate(st.session_state.rename_mappings):
                    rm_col1, rm_col2, rm_col3 = st.columns([4, 4, 1])
                    
                    st.session_state.rename_mappings[i]["old"] = rm_col1.selectbox(
                        f"Current Name {i}", options=available_versions, 
                        key=f"rename_old_{i}", 
                        index=available_versions.index(mapping["old"]) if mapping["old"] in available_versions else None,
                        placeholder="Select Version", label_visibility="collapsed"
                    )
                    
                    st.session_state.rename_mappings[i]["new"] = rm_col2.text_input(
                        f"New Name {i}", value=mapping["new"], 
                        key=f"rename_new_{i}", 
                        placeholder="Enter New Name", label_visibility="collapsed"
                    )
                    
                    if rm_col3.button("X", key=f"remove_rename_{i}", use_container_width=True):
                        remove_rename_row(i)
                        st.rerun()

                if st.button("➕ Add Rename Row", use_container_width=True, key="add_rename_btn"):
                    add_rename_row()
                    st.rerun()

                st.divider()

                # Processing renames
                active_renames = [m for m in st.session_state.rename_mappings if m["old"] and m["new"].strip()]
                
                if active_renames:
                    if st.button("🚀 Execute Batch Rename", use_container_width=True, type="primary"):
                        success_count = 0
                        for p in current_selection_list:
                            with st.status(f"Renaming in {p}...", expanded=False) as status:
                                proj_versions = get_versions_cached(username, config_tuple, p)
                                for mapping in active_renames:
                                    old_n = mapping["old"]
                                    new_n = mapping["new"].strip()
                                    target = next((v for v in proj_versions if v["name"] == old_n), None)
                                    if target:
                                        if jira_utils.rename_version(st.session_state.jira_config, target["id"], p, old_n, new_n):
                                            st.success(f"{p}: Renamed {old_n} -> {new_n}")
                                            success_count += 1
                                        else:
                                            st.error(f"{p}: Failed to rename {old_n}")
                                    else:
                                        st.warning(f"{p}: '{old_n}' not found.")
                                status.update(label=f"Completed {p}", state="complete")
                        
                        st.cache_data.clear()
                        st.success(f"🎉 Batch rename complete! ({success_count} actions)")
                        st.session_state.last_rename_mappings = active_renames

                # Navigation Handoff
                if st.session_state.get("last_rename_mappings"):
                    st.info("💡 You have successfully renamed versions. Would you like to update these versions in your Jira Filters?")
                    if st.button("🔍 Go to: Update Filters for these renames", use_container_width=True):
                        st.session_state.filter_mappings = [m.copy() for m in st.session_state.last_rename_mappings]
                        st.query_params["tab"] = "🔍 Update Filters"
                        st.rerun()

        with tab_v4:
            st.header("🔍 Batch Update Filter JQL")
            
            filter_names_raw = st.text_input("Enter Filter Names (comma separated)", placeholder="Filter Name 1, Filter Name 2", key="filter_names_input")
            target_names = [n.strip() for n in filter_names_raw.split(",") if n.strip()]
            
            selected_filters = []
            
            if target_names:
                if st.button("🔍 Validate and Load Filters", use_container_width=True):
                    resolved = []
                    with st.status("Validating filters...") as status:
                        for name in target_names:
                            f = jira_utils.get_filter_by_name(st.session_state.jira_config, name)
                            if f:
                                resolved.append(f)
                                st.success(f"Found and validated: {name}")
                            else:
                                st.warning(f"Filter '{name}' not found.")
                    
                    if resolved:
                        st.session_state.manual_filters = resolved
                        st.success(f"Loaded {len(resolved)} valid filters.")
                    else:
                        st.error("No valid filters were found from the provided names.")

            if "manual_filters" in st.session_state:
                selected_filters = st.session_state.manual_filters
                st.write(f"**Loaded filters:** {', '.join([f['name'] for f in selected_filters])}")

            # Replacement Logic
            if selected_filters:
                st.divider()
                st.subheader("Version renaming")

                # Initialize mappings in session state
                if 'filter_mappings' not in st.session_state:
                    st.session_state.filter_mappings = [{"old": None, "new": ""}]
                
                # Option to reset mappings
                if st.button("🧹 Clear All Mappings", key="clear_filter_maps"):
                    st.session_state.filter_mappings = [{"old": None, "new": ""}]
                    st.rerun()

                # Fetch versions for active workspace to populate dropdowns
                with st.spinner("Loading versions for active workspace..."):
                    all_v_names = get_versions_for_projects_cached(username, config_tuple, current_selection_list)

                # Function to add a row
                def add_mapping_row():
                    st.session_state.filter_mappings.append({"old": None, "new": ""})

                # Function to remove a row
                def remove_mapping_row(index):
                    if len(st.session_state.filter_mappings) > 1:
                        st.session_state.filter_mappings.pop(index)

                # Render Header Row
                h_col1, h_col2, h_col3 = st.columns([4, 4, 1])
                h_col1.write("**Old Version**")
                h_col2.write("**New Version**")

                # Render mapping rows
                for i, mapping in enumerate(st.session_state.filter_mappings):
                    m_col1, m_col2, m_col3 = st.columns([4, 4, 1])
                    
                    st.session_state.filter_mappings[i]["old"] = m_col1.selectbox(
                        f"Old Version {i+1}", 
                        options=all_v_names, 
                        key=f"old_v_map_{i}", 
                        index=all_v_names.index(mapping["old"]) if mapping["old"] in all_v_names else None,
                        placeholder="Select Old Version",
                        label_visibility="collapsed"
                    )
                    
                    st.session_state.filter_mappings[i]["new"] = m_col2.text_input(
                        f"New Version {i+1}", 
                        value=mapping["new"], 
                        key=f"new_v_map_{i}", 
                        placeholder="Enter New Version",
                        label_visibility="collapsed"
                    )
                    
                    if m_col3.button("X", key=f"remove_map_{i}", help="Remove this mapping", use_container_width=True):
                        remove_mapping_row(i)
                        st.rerun()

                if st.button("➕ Add Mapping Row", use_container_width=True):
                    add_mapping_row()
                    st.rerun()

                st.divider()

                # Gather and group mappings
                final_mappings = {} # old -> list of news
                for m in st.session_state.filter_mappings:
                    if m["old"] and m["new"].strip():
                        old_v = m["old"]
                        new_v = m["new"].strip()
                        if old_v not in final_mappings:
                            final_mappings[old_v] = []
                        if new_v not in final_mappings[old_v]:
                            final_mappings[old_v].append(new_v)

                if final_mappings:
                    if st.button("🚀 Update All Loaded Filters", type="primary", use_container_width=True):
                        for f in selected_filters:
                            with st.status(f"Processing filter: {f['name']}...", expanded=True) as status:
                                current_jql = f.get("jql", "")
                                new_jql = current_jql
                                
                                # Apply all unique old version replacements
                                for old_v, new_v_list in final_mappings.items():
                                    new_jql = update_jql_version(new_jql, old_v, new_v_list)
                                
                                if new_jql == current_jql:
                                    st.info(f"No specified old versions found in JQL for {f['name']}.")
                                else:
                                    st.write(f"**Original JQL:** `{current_jql}`")
                                    st.write(f"**Updated JQL:** `{new_jql}`")
                                    
                                    if jira_utils.update_filter_jql(st.session_state.jira_config, f["id"], new_jql):
                                        st.success(f"Successfully updated filter: {f['name']}")
                                        f["jql"] = new_jql
                                    else:
                                        st.error(f"Failed to update filter: {f['name']}")
                                
                                status.update(label=f"Finished {f['name']}", state="complete")
                        
                        st.success("🎉 Batch filter update completed!")

if __name__ == "__main__":
    main()
