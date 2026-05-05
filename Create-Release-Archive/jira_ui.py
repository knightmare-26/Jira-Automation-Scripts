import streamlit as st
import pandas as pd
import jira_utils
import jira_config
import os
import logging
import json
import streamlit_authenticator as stauth
import yaml
import importlib
from yaml.loader import SafeLoader
from supabase import create_client, Client
import time
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

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
            response = supabase.table("user_settings").select("managed_projects").eq("username", username).execute()
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
            supabase.table("user_settings").upsert({
                "username": username,
                "managed_projects": projects
            }).execute()
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
            response = supabase.table("user_settings").select("shortcuts").eq("username", username).execute()
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
            supabase.table("user_settings").upsert({
                "username": username,
                "shortcuts": shortcuts
            }).execute()
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
            response = supabase.table("app_config").select("content").eq("id", f"jira_config_{username}").execute()
            if response.data:
                content = response.data[0].get("content", {})
                if content:
                    raw_token = content.get("JIRA_API_TOKEN")
                    decrypted_token = decrypt_data(raw_token)
                    
                    # If we just decrypted a plaintext token, trigger a silent re-save to encrypt it
                    if raw_token and raw_token == decrypted_token and cipher_suite:
                        save_jira_config(username, content.get("JIRA_BASE_URL"), content.get("JIRA_EMAIL"), decrypted_token)

                    return {
                        "JIRA_BASE_URL": content.get("JIRA_BASE_URL"),
                        "JIRA_EMAIL": content.get("JIRA_EMAIL"),
                        "JIRA_API_TOKEN": decrypted_token,
                        "API_BASE": f"{content.get('JIRA_BASE_URL')}/rest/api/3" if content.get('JIRA_BASE_URL') else None,
                        "AUTH": (content.get('JIRA_EMAIL'), decrypted_token) if content.get('JIRA_EMAIL') and decrypted_token else None,
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
    config_data = {
        "JIRA_BASE_URL": url,
        "JIRA_EMAIL": email,
        "JIRA_API_TOKEN": encrypted_token
    }
    if supabase:
        try:
            supabase.table("app_config").upsert({
                "id": f"jira_config_{username}",
                "content": config_data
            }).execute()
            
            st.session_state.jira_config = {
                "JIRA_BASE_URL": url,
                "JIRA_EMAIL": email,
                "JIRA_API_TOKEN": token, # Keep plaintext in session state for API calls
                "API_BASE": f"{url}/rest/api/3" if url else None,
                "AUTH": (email, token) if email and token else None,
                "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
            }
            st.cache_data.clear()
            return True
        except Exception as e:
            logger.error(f"Error saving Jira config to Supabase for {username}: {e}")
            st.error("Failed to save configuration to cloud.")
    return False

def save_users_config(config):
    """Save user configuration locally and granularly to Supabase."""
    try:
        with open('users.yaml', 'w') as file:
            yaml.dump(config, file, default_flow_style=False)
    except Exception as e:
        logger.error(f"Error saving users config locally: {e}")
        return False
    
    if supabase:
        try:
            # Phase 3: Save individual user records instead of one giant file
            # This prevents User A from overwriting User B's new registration
            usernames = config.get('credentials', {}).get('usernames', {})
            for username, user_data in usernames.items():
                supabase.table("app_config").upsert({
                    "id": f"auth_user_{username}",
                    "content": user_data
                }).execute()
            
            # Also save the non-user config parts (cookie, etc)
            base_config = {k: v for k, v in config.items() if k != 'credentials'}
            supabase.table("app_config").upsert({
                "id": "auth_base_config",
                "content": base_config
            }).execute()
        except Exception as e:
            logger.error(f"Error syncing users to cloud: {e}")
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

def main():
    if 'view' not in st.session_state:
        st.session_state.view = 'landing'
    
    if st.session_state.view == 'landing':
        render_landing_page()
        return

    if 'current_page' not in st.session_state:
        st.session_state.current_page = "📂 Manage Projects"

    # --- Initial Cloud Sync (Granular) ---
    if 'auth_synced' not in st.session_state:
        if supabase:
            try:
                # 1. Load base config (cookies, etc)
                response_base = supabase.table("app_config").select("content").eq("id", "auth_base_config").execute()
                
                # 2. Load all individual users
                response_users = supabase.table("app_config").select("id", "content").filter("id", "like", "auth_user_%").execute()
                
                if response_users.data:
                    # Reconstruct the full config object
                    new_config = {
                        'credentials': {'usernames': {}},
                        'cookie': {'expiry_days': 0.0208, 'key': 'some_signature_key', 'name': 'jira_manager_cookie'},
                        'preauthorized': {'emails': []}
                    }
                    
                    if response_base.data:
                        new_config.update(response_base.data[0].get("content", {}))
                    
                    for row in response_users.data:
                        username = row['id'].replace("auth_user_", "")
                        new_config['credentials']['usernames'][username] = row['content']
                    
                    with open('users.yaml', 'w') as file:
                        yaml.dump(new_config, file, default_flow_style=False)
                
                # Backward compatibility: Check for old monolithic file if no granular users found
                elif not response_users.data:
                    response_old = supabase.table("app_config").select("content").eq("id", "users_config").execute()
                    if response_old.data:
                        cloud_config = response_old.data[0].get("content")
                        with open('users.yaml', 'w') as file:
                            yaml.dump(cloud_config, file, default_flow_style=False)
                        # Immediately migrate to granular format
                        save_users_config(cloud_config)

            except Exception as e:
                logger.error(f"Cloud auth config pull failed: {e}")
        st.session_state.auth_synced = True

    if not os.path.exists('users.yaml'):
        initial_config = {
            'credentials': {'usernames': {}},
            'cookie': {'expiry_days': 0.0208, 'key': 'some_signature_key', 'name': 'jira_manager_cookie'},
            'preauthorized': {'emails': []}
        }
        save_users_config(initial_config)

    with open('users.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)

    config['cookie']['expiry_days'] = 0.0208

    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )

    if st.session_state.get("authentication_status") != True:
        if st.sidebar.button("⬅️ Back to Home"):
            st.session_state.view = 'landing'
            st.rerun()

        # Clear user-specific state when not authenticated to ensure a fresh start on login
        st.session_state.selected_projects = set()
        st.session_state.selected_versions = []
        for key in list(st.session_state.keys()):
            if key.startswith("cb_"):
                del st.session_state[key]
        st.session_state.last_user = None

        tab_login, tab_signup = st.tabs(["🔐 Sign In", "📝 Sign Up"])
        
        with tab_login:
            try:
                authenticator.login(location='main')
            except Exception as e:
                st.error(f"Login widget error: {e}")
            
            if st.session_state.get("authentication_status") == False:
                st.error('Username/password is incorrect')
            elif st.session_state.get("authentication_status") == True:
                st.session_state.view = 'app'
                st.rerun()
        
        with tab_signup:
            st.markdown("""
                <style>
                div[data-testid="stTextInput"]:has(label:contains("Name")) {
                    display: none;
                }
                </style>
                """, unsafe_allow_html=True)
            try:
                if authenticator.register_user(location='main'):
                    st.success('User registered successfully! You can now log in.')
                    save_users_config(config) 
            except Exception as e:
                st.error(f"Registration failed: {e}")
        
        if st.session_state.get("authentication_status") != True:
            return

    name = st.session_state["name"]
    username = st.session_state["username"]

    if 'last_user' not in st.session_state or st.session_state.last_user != username:
        st.session_state.selected_projects = set()
        st.session_state.selected_versions = []
        for key in list(st.session_state.keys()):
            if key.startswith("cb_"):
                del st.session_state[key]
        st.session_state.last_user = username

    if st.session_state.get("is_guest"):
        st.sidebar.title("Guest Mode (Session Only)")
        if st.sidebar.button("🔐 Log in to save settings"):
            # Reset guest state and go to login
            st.session_state.is_guest = False
            st.session_state.authentication_status = None
            st.session_state.username = None
            st.session_state.name = None
            st.session_state.view = 'login'
            st.cache_data.clear()
            st.rerun()
    else:
        st.sidebar.title(f"Welcome {name}")
        authenticator.logout('Logout', location='sidebar')

    if 'jira_config' not in st.session_state:
        st.session_state.jira_config = load_jira_config(username)
        cleanup_old_logs()

    config_tuple = tuple(st.session_state.jira_config.items())

    is_config_valid = all([
        st.session_state.jira_config.get("JIRA_BASE_URL"), 
        st.session_state.jira_config.get("JIRA_EMAIL"), 
        st.session_state.jira_config.get("JIRA_API_TOKEN")
    ])
    
    if not is_config_valid and st.session_state.get('current_page') != "⚙️ Config":
        st.warning("⚠️ **Action Required:** Jira configuration is incomplete. Please set up your credentials below.")
        st.session_state.current_page = "⚙️ Config"
        st.rerun()

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

    page = st.sidebar.radio("Navigation", options=nav_options, index=current_index)
    if page != st.session_state.current_page:
        st.session_state.current_page = page
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
        st.info("Update your Jira connection details here.")
        url = st.text_input("Jira Base URL", value=st.session_state.jira_config.get("JIRA_BASE_URL") or "", help="The URL of your Jira instance (e.g., https://yourcompany.atlassian.net)")
        email = st.text_input("Jira Email", value=st.session_state.jira_config.get("JIRA_EMAIL") or "", help="The email address associated with your Jira account")
        token = st.text_input("Jira API Token", value=st.session_state.jira_config.get("JIRA_API_TOKEN") or "", type="password", help="Your personal API token. You can create one at: https://id.atlassian.com/manage-profile/security/api-tokens")
        if st.button("Save Configuration", type="primary"):
            if save_jira_config(username, url, email, token):
                st.success("✅ Configuration saved successfully! Redirecting...")
                time.sleep(1) 
                st.session_state.current_page = "📂 Manage Projects"
                st.rerun()

    elif page == "📂 Manage Projects":
        st.title("📂 Manage Projects")
        tab1, tab2 = st.tabs(["🎯 Active Workspace", "⚙️ Manage Tracked Projects"])

        with tab1:
            st.header("🎯 Select Active Projects")
            current_selection = sorted(list(st.session_state.selected_projects))
            if not all_projects:
                st.info("💡 **Getting Started:** You haven't tracked any projects yet. Go to the **'Manage Tracked Projects'** tab to add some from your Jira account.")
            elif current_selection:
                st.success(f"✅ **{len(current_selection)} Projects Active:** {', '.join(current_selection)}")

            if all_projects:
                col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 4])
                if col_ctrl1.button("Select All Tracked", use_container_width=True):
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
                            if st.session_state[f"cb_{key}"]:
                                st.session_state.selected_projects.add(key)
                            else:
                                st.session_state.selected_projects.discard(key)
                        st.checkbox(f"**{p_key}**", key=f"cb_{p_key}", help=p['name'], on_change=on_change)

                if current_selection:
                    st.divider()
                    if st.button("🚀 Go to: Manage Versions", use_container_width=True, type="primary"):
                        st.session_state.current_page = "🚀 Manage Versions"
                        st.rerun()

        with tab2:
            st.subheader("➕ Add Projects from Jira")
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
                    st.info("All your Jira projects are already being tracked.")
            else:
                st.error("Could not fetch projects from Jira. Check your Config.")

            st.divider()
            if all_projects:
                st.subheader("🗑️ Remove Tracked Projects")
                options_rm = [f"{p['key']} | {p['name']}" for p in all_projects]
                selected_to_rm = st.multiselect("Search and select projects to remove:", options=options_rm, key="rm_multiselect")
                if selected_to_rm:
                    if st.button("🗑️ Confirm Removing Selected Projects", type="primary", use_container_width=True):
                        keys_to_rm = [s.split(" | ")[0] for s in selected_to_rm]
                        managed_keys = load_managed_projects(username)
                        updated_managed = [k for k in managed_keys if k not in keys_to_rm]
                        if save_managed_projects(username, updated_managed):
                            for k in keys_to_rm:
                                st.session_state.selected_projects.discard(k)
                            st.success(f"🗑️ Removed {len(keys_to_rm)} projects!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()

    elif page == "🚀 Manage Versions":
        st.title("🚀 Manage Versions")
        tab_v1, tab_v2, tab_v3 = st.tabs(["🚀 Create Versions", "📦 Release/Archive", "✏️ Rename"])

        current_selection_list = sorted(list(st.session_state.selected_projects))

        with tab_v1:
            st.header("🚀 Create New Versions")
            if not current_selection_list:
                st.warning("⚠️ No projects selected. Please go to the **Active Workspace** tab to select projects.")
            else:
                st.write(f"**Active Workspace:** {', '.join(current_selection_list)}")
                new_versions_raw = st.text_input("Enter Version Names (comma separated)", placeholder="e.g. 2026Train1, 2026Train2", key="new_versions_input")
                final_versions = [v.strip() for v in new_versions_raw.split(",") if v.strip()]
                col_date1, col_date2 = st.columns(2)
                start_date = col_date1.date_input("Start Date (Optional)", value=None, key="start_date_input")
                end_date = col_date2.date_input("Release Date (Optional)", value=None, key="end_date_input")
                
                if final_versions:
                    st.divider()
                    st.write(f"**Planned Versions:** {', '.join(final_versions)}")
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
                st.warning("⚠️ No projects selected. Please go to the **Active Workspace** tab to select projects.")
            else:
                st.write(f"**Active Workspace:** {', '.join(current_selection_list)}")
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
                    st.write(f"Selected Fix Versions: **{', '.join(target_versions)}**")
                    st.warning("These actions will be applied to all selected versions across all active projects.")
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
                st.warning("⚠️ No projects selected. Please go to the **Active Workspace** tab to select projects.")
            else:
                st.write(f"**Active Workspace:** {', '.join(current_selection_list)}")
                with st.spinner("Loading versions..."):
                    all_v_details = []
                    for p in current_selection_list:
                        all_v_details.extend(jira_utils.get_versions(st.session_state.jira_config, p))
                    available_versions = sorted(list(set([v['name'] for v in all_v_details if not v.get("archived")])))
                
                target_versions_rename = st.multiselect("Select Versions to Rename", options=available_versions, key="version_multiselect_v3")
                new_version_name = st.text_input("Enter New Version Name", placeholder="e.g. 2026Train1-Final")
                
                if target_versions_rename and new_version_name:
                    st.divider()
                    if st.button("✏️ Rename Versions", use_container_width=True, type="primary"):
                        for p in current_selection_list:
                            with st.status(f"Renaming in {p}...", expanded=False) as status:
                                proj_versions = get_versions_cached(username, config_tuple, p)
                                for v_name in target_versions_rename:
                                    target = next((v for v in proj_versions if v["name"] == v_name), None)
                                    if target:
                                        if jira_utils.rename_version(st.session_state.jira_config, target["id"], p, v_name, new_version_name):
                                            st.success(f"{p}: Renamed {v_name} to {new_version_name}")
                                            st.cache_data.clear()
                                        else:
                                            st.error(f"{p}: Failed to rename {v_name}")
                                    else:
                                        st.warning(f"{p}: Version {v_name} not found.")
                                status.update(label=f"Completed {p}", state="complete")
                        st.success("🎉 All selected versions renamed successfully!")

if __name__ == "__main__":
    main()
