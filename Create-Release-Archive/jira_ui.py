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

import time
from datetime import datetime, timedelta

def cleanup_old_logs(log_file="jira_automation_runs.log", days=30):
    if not os.path.exists(log_file):
        return
    
    cutoff = datetime.now() - timedelta(days=days)
    new_logs = []
    
    try:
        with open(log_file, "r") as f:
            for line in f:
                # Assuming log format starts with timestamp, e.g., "2026-04-22 14:30:12"
                try:
                    log_date_str = line.split(" [")[0]
                    log_date = datetime.strptime(log_date_str, "%Y-%m-%d %H:%M:%S")
                    if log_date >= cutoff:
                        new_logs.append(line)
                except (ValueError, IndexError):
                    # Keep lines that don't match expected timestamp format
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

file_handler = logging.FileHandler("jira_automation_runs.log")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(file_handler)

@st.cache_data(ttl=1800)
def load_managed_projects(username):
    # Try Supabase first
    if supabase:
        try:
            response = supabase.table("user_settings").select("managed_projects").eq("username", username).execute()
            if response.data:
                return response.data[0].get("managed_projects", [])
        except Exception as e:
            logger.error(f"Supabase load error for {username}: {e}")

    # Fallback to local file
    filename = get_user_projects_file(username)
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading managed projects for {username}: {e}")
    return []

def save_managed_projects(username, projects):
    # Save to Supabase first
    if supabase:
        try:
            supabase.table("user_settings").upsert({
                "username": username,
                "managed_projects": projects
            }).execute()
            st.cache_data.clear() # Clear cache so changes reflect
            return True # Success in cloud
        except Exception as e:
            logger.error(f"Supabase save error for {username}: {e}")

    # Fallback: Save to local file
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
    # Try Supabase first
    if supabase:
        try:
            response = supabase.table("user_settings").select("shortcuts").eq("username", username).execute()
            if response.data:
                return response.data[0].get("shortcuts", {})
        except Exception as e:
            logger.error(f"Supabase load shortcuts error for {username}: {e}")

    # Fallback to local file
    filename = get_user_shortcuts_file(username)
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading shortcuts for {username}: {e}")
    return {}

def save_shortcuts(username, shortcuts):
    # Save to Supabase first
    if supabase:
        try:
            supabase.table("user_settings").upsert({
                "username": username,
                "shortcuts": shortcuts
            }).execute()
        except Exception as e:
            logger.error(f"Supabase save shortcuts error for {username}: {e}")

    # Always save to local file as backup
    filename = get_user_shortcuts_file(username)
    try:
        with open(filename, "w") as f:
            json.dump(shortcuts, f, indent=4)
        st.cache_data.clear() # Clear cache
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
def get_all_jira_projects_cached(config_tuple):
    """Fetches ALL projects from Jira API using provided config."""
    config = dict(config_tuple)
    return jira_utils.get_projects(config)

@st.cache_data(ttl=3600)
def get_managed_projects_cached(username, config_tuple):
    """Returns only projects that are in the user's managed list."""
    all_projects = get_all_jira_projects_cached(config_tuple)
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
def get_versions_cached(config_tuple, project_key):
    """Fetches versions for a project using provided config."""
    config = dict(config_tuple)
    return jira_utils.get_versions(config, project_key)

def get_versions_for_projects_cached(config_tuple, project_keys):
    """Fetches all version names for multiple projects."""
    if not project_keys:
        return []
    all_version_names = set()
    for key in project_keys:
        versions = get_versions_cached(config_tuple, key)
        for v in versions:
            all_version_names.add(v.get('name'))
    return sorted(list(all_version_names))

def load_jira_config(username):
    """Load private Jira configuration for a specific user from Supabase."""
    if supabase:
        try:
            # Use app_config with a user-specific ID to avoid schema constraints
            response = supabase.table("app_config").select("content").eq("id", f"jira_config_{username}").execute()
            if response.data:
                content = response.data[0].get("content", {})
                if content:
                    return {
                        "JIRA_BASE_URL": content.get("JIRA_BASE_URL"),
                        "JIRA_EMAIL": content.get("JIRA_EMAIL"),
                        "JIRA_API_TOKEN": content.get("JIRA_API_TOKEN"),
                        "API_BASE": f"{content.get('JIRA_BASE_URL')}/rest/api/3" if content.get('JIRA_BASE_URL') else None,
                        "AUTH": (content.get('JIRA_EMAIL'), content.get('JIRA_API_TOKEN')) if content.get('JIRA_EMAIL') and content.get('JIRA_API_TOKEN') else None,
                        "HEADERS": {"Accept": "application/json", "Content-Type": "application/json"}
                    }
        except Exception as e:
            logger.error(f"Error loading Jira config from Supabase for {username}: {e}")
    return {"JIRA_BASE_URL": None, "JIRA_EMAIL": None, "JIRA_API_TOKEN": None, "API_BASE": None, "AUTH": None, "HEADERS": None}

def save_jira_config(username, url, email, token):
    """Save private Jira configuration for a specific user to Supabase."""
    config_data = {
        "JIRA_BASE_URL": url,
        "JIRA_EMAIL": email,
        "JIRA_API_TOKEN": token
    }
    if supabase:
        try:
            # Store in app_config using a unique ID per user for isolation
            supabase.table("app_config").upsert({
                "id": f"jira_config_{username}",
                "content": config_data
            }).execute()
            
            # Update local session state
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
            st.error("Failed to save configuration to cloud.")
    return False
def save_users_config(config):
    # Save to local file
    try:
        with open('users.yaml', 'w') as file:
            yaml.dump(config, file, default_flow_style=False)
    except Exception as e:
        logger.error(f"Error saving users config locally: {e}")
        return False
    
    # Save to Supabase for cloud persistence
    if supabase:
        try:
            # We store the entire config as one record for easy syncing
            supabase.table("app_config").upsert({
                "id": "users_config",
                "content": config
            }).execute()
        except Exception as e:
            logger.error(f"Error syncing users to cloud: {e}")
    return True

def main():
    # Initialize session state for current page first thing
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "📂 Manage Projects"

    # --- Initial Cloud Sync (Authentication Only) ---
    # Sync auth config from cloud only once per browser session
    if 'auth_synced' not in st.session_state:
        if supabase:
            try:
                response = supabase.table("app_config").select("content").eq("id", "users_config").execute()
                if response.data:
                    cloud_config = response.data[0].get("content")
                    with open('users.yaml', 'w') as file:
                        yaml.dump(cloud_config, file, default_flow_style=False)
            except Exception as e:
                logger.error(f"Cloud auth config pull failed: {e}")
        st.session_state.auth_synced = True

    if not os.path.exists('users.yaml'):
        initial_config = {
            'credentials': {'usernames': {}},
            'cookie': {'expiry_days': 30, 'key': 'some_signature_key', 'name': 'jira_manager_cookie'},
            'preauthorized': {'emails': []}
        }
        save_users_config(initial_config)

    with open('users.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)

    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )

    # --- Login/Sign Up Logic ---
    if st.session_state.get("authentication_status") != True:
        tab_login, tab_signup = st.tabs(["🔐 Login", "📝 Sign Up"])
        
        with tab_login:
            # The latest version of streamlit-authenticator uses location as the first arg or keyword
            try:
                authenticator.login(location='main')
            except Exception as e:
                st.error(f"Login widget error: {e}")

            if st.session_state.get("authentication_status") == False:
                st.error('Username/password is incorrect')
            elif st.session_state.get("authentication_status") == None:
                st.info("Please log in to continue.")

        with tab_signup:
            try:
                # Customizing fields to hide "Name" if possible, or just keep it simple.
                # In many versions, you can pass a dictionary to define labels or presence.
                # If we can't hide "Name", we'll at least label it clearly.
                if authenticator.register_user(location='main'):
                    st.success('User registered successfully! You can now log in.')
                    
                    # After registration, the 'config' dictionary is updated by the library.
                    # We ensure 'name' isn't empty if the user skipped it (though usually it's required)
                    save_users_config(config) 
            except Exception as e:
                if "Must contain Name" in str(e):
                    st.error("Please ensure all fields are filled out correctly.")
                else:
                    st.error(f"Registration failed: {e}")
        
        if st.session_state.get("authentication_status") != True:
            return

    # --- Authenticated App ---
    name = st.session_state["name"]
    username = st.session_state["username"]
    
    st.sidebar.title(f"Welcome {name}")
    authenticator.logout('Logout', location='sidebar')

    # Load User-Specific Jira Config if not already in session
    if 'jira_config' not in st.session_state:
        st.session_state.jira_config = load_jira_config(username)
        # Run cleanup once at session start
        cleanup_old_logs()

    # Convert config to a hashable tuple for caching keys
    config_tuple = tuple(st.session_state.jira_config.items())

    # --- Global Config Check ---
    # Refresh config validity from session state
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
    
    # Ensure session state checkboxes are synced with current selections
    for k in project_keys:
        if f"cb_{k}" not in st.session_state:
            st.session_state[f"cb_{k}"] = k in st.session_state.selected_projects

    if 'selected_versions' not in st.session_state:
        st.session_state.selected_versions = []

    # --- Sidebar Navigation ---
    st.sidebar.title("🎯 Jira Manager")
    
    # Define available pages
    if is_config_valid:
        nav_options = ["📂 Manage Projects", "🚀 Create Versions", "📦 Release/Archive", "⚙️ Config"]
    else:
        nav_options = ["⚙️ Config"]
    
    # Ensure current_page is valid
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

    st.sidebar.divider()
    
    # Only show shortcuts and projects-related logic if config is valid
    if is_config_valid:
        st.sidebar.header("Quick Shortcuts")
        shortcuts = load_shortcuts(username)
        for s_name, data in shortcuts.items():
            col1, col2 = st.sidebar.columns([4, 1])
            if col1.button(f"📍 {s_name}", key=f"apply_{s_name}", use_container_width=True):
                new_proj_list = data.get("projects", [])
                st.session_state.selected_projects = set(new_proj_list)
                st.session_state.selected_versions = data.get("versions", [])
                # Sync individual checkbox states in session_state
                for k in project_keys:
                    st.session_state[f"cb_{k}"] = k in st.session_state.selected_projects
                st.session_state.current_page = "📂 Manage Projects"
                st.rerun()
            if col2.button("🗑️", key=f"del_{s_name}"):
                if delete_shortcut(username, s_name):
                    st.rerun()

    # --- Page Content ---
    if page == "⚙️ Config":
        st.title("⚙️ Jira Configuration")
        st.info("Update your private Jira connection details here.")
        url = st.text_input("Jira Base URL", value=st.session_state.jira_config.get("JIRA_BASE_URL") or "")
        email = st.text_input("Jira Email", value=st.session_state.jira_config.get("JIRA_EMAIL") or "")
        token = st.text_input("Jira API Token", value=st.session_state.jira_config.get("JIRA_API_TOKEN") or "", type="password")
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
            
            # Consolidate status messages
            current_selection = list(st.session_state.selected_projects)
            
            if not all_projects:
                st.info("💡 **Getting Started:** You haven't tracked any projects yet. Go to the **'Manage Tracked Projects'** tab to add some from your Jira account.")
            elif not current_selection:
                pass # Removed redundant select projects info
            else:
                st.success(f"✅ **{len(current_selection)} Projects Active:** {', '.join(sorted(current_selection))}")

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

                # Grid-based Checkbox Layout
                cols = st.columns(4)
                for idx, p in enumerate(all_projects):
                    with cols[idx % 4]:
                        p_key = p['key']
                        
                        def on_change(key=p_key):
                            if st.session_state[f"cb_{key}"]:
                                st.session_state.selected_projects.add(key)
                            else:
                                st.session_state.selected_projects.discard(key)

                        st.checkbox(
                            f"**{p_key}**", 
                            key=f"cb_{p_key}", 
                            help=p['name'],
                            on_change=on_change
                        )

                if current_selection:
                    st.divider()
                    with st.expander("💾 Save Current Selection as Shortcut"):
                        shortcut_name = st.text_input("Shortcut Name")
                        if st.button("Save Shortcut"):
                            if shortcut_name:
                                if save_shortcut(username, shortcut_name, current_selection, st.session_state.selected_versions):
                                    st.success(f"Saved shortcut: {shortcut_name}")
                                    st.rerun()
                            else:
                                st.error("Please provide a name for the shortcut.")

        with tab2:
            st.header("Add or remove Active projects:")
            
            # Export/Import Section for "Per-User" feel on shared servers
            with st.expander("💾 Personalize your Workspace (Export/Import)"):
                st.write("Use these to move your settings between computers or servers.")
                col_ex1, col_ex2 = st.columns(2)
                
                # Export
                workspace_data = {
                    "managed_projects": load_managed_projects(username),
                    "shortcuts": load_shortcuts(username)
                }
                workspace_json = json.dumps(workspace_data, indent=4)
                col_ex1.download_button(
                    label="📥 Export My Workspace",
                    data=workspace_json,
                    file_name=f"jira_workspace_{username}.json",
                    mime="application/json",
                    use_container_width=True,
                    help="Save your tracked projects and shortcuts to your computer."
                )
                
                # Import
                uploaded_file = col_ex2.file_uploader("📤 Import Workspace", type="json", label_visibility="collapsed")
                if uploaded_file is not None:
                    try:
                        data = json.load(uploaded_file)
                        if "managed_projects" in data and "shortcuts" in data:
                            save_managed_projects(username, data["managed_projects"])
                            save_shortcuts(username, data["shortcuts"])
                            st.success("Workspace imported! Reloading...")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Invalid workspace file.")
                    except Exception as e:
                        st.error(f"Error importing: {e}")

            st.divider()

            # Add Project Section
            st.subheader("➕ Add Projects from Jira")
            all_jira_projects = get_all_jira_projects_cached(config_tuple)
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

            # Remove Project Section
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

        # --- Navigation Footer ---
        if current_selection:
            st.divider()
            st.write("### Next Steps")
            col_nav1, col_nav2 = st.columns(2)
            if col_nav1.button("Go to: Create Versions 🚀", use_container_width=True):
                st.session_state.current_page = "🚀 Create Versions"
                st.rerun()
            if col_nav2.button("Go to: Release/Archive 📦", use_container_width=True):
                st.session_state.current_page = "📦 Release/Archive"
                st.rerun()

    elif page == "🚀 Create Versions":
        st.title("🚀 Create New Versions")
        current_selection = sorted(list(st.session_state.selected_projects))
        
        if not current_selection:
            st.warning("⚠️ No projects selected. Please go to the **Manage Projects** page to select projects.")
        else:
            st.write(f"**Active Workspace:** {', '.join(current_selection)}")
            
            st.header("1. Define Versions")
            new_versions_raw = st.text_input("Enter Version Names (comma separated)", placeholder="e.g. 2026Train1, 2026Train2")
            final_versions = [v.strip() for v in new_versions_raw.split(",") if v.strip()]

            col_date1, col_date2 = st.columns(2)
            start_date = col_date1.date_input("Start Date (Optional)", value=None)
            end_date = col_date2.date_input("Release Date (Optional)", value=None)

            if final_versions:
                st.write(f"**Planned Versions:** {', '.join(final_versions)}")
                st.session_state.selected_versions = final_versions

            st.header("2. Execution")
            if st.button("🚀 Create Versions Across Active Projects", use_container_width=True, type="primary"):
                if not final_versions:
                    st.error("Please define at least one version name.")
                else:
                    start_date_str = start_date.isoformat() if start_date else None
                    end_date_str = end_date.isoformat() if end_date else None
                    
                    for p in current_selection:
                        with st.status(f"Processing {p}...", expanded=True) as status:
                            existing_versions_list = get_versions_cached(config_tuple, p)
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

    elif page == "📦 Release/Archive":
        st.title("📦 Release & Archive Versions")
        current_selection = sorted(list(st.session_state.selected_projects))
        
        if not current_selection:
            st.warning("⚠️ No projects selected. Please go to the **Manage Projects** page to select projects.")
        else:
            st.write(f"**Active Workspace:** {', '.join(current_selection)}")

            st.header("1. Select Fix Versions")
            # 1. Version filtering options
            show_released_only = st.checkbox("Show only Released versions (not yet archived)")
            
            # Fetch versions and filter
            with st.spinner("Loading versions..."):
                all_v_list = get_versions_for_projects_cached(config_tuple, current_selection)
                # Fetch full data to check status
                all_v_details = []
                for p in current_selection:
                    all_v_details.extend(jira_utils.get_versions(st.session_state.jira_config, p))
                
                if show_released_only:
                    # Filter: Released=True, Archived=False
                    available_versions = [v['name'] for v in all_v_details if v.get("released") and not v.get("archived")]
                else:
                    # Filter: Released=False AND Archived=False
                    available_versions = [v['name'] for v in all_v_details if not v.get("released") and not v.get("archived")]
                
                available_versions = sorted(list(set(available_versions)))
            
            target_versions = st.multiselect(
                "Fix Versions",
                options=available_versions,
                key="version_multiselect"
            )
            
            st.session_state.selected_versions = target_versions

            if target_versions:
                st.divider()
                st.header("2. Actions")
                st.write(f"Selected Fix Versions: **{', '.join(target_versions)}**")
                st.warning("These actions will be applied to all selected versions across all active projects.")
                
                rel_col, arc_col = st.columns(2)
                
                if rel_col.button("✅ Release Versions", use_container_width=True, type="primary"):
                    for p in current_selection:
                        with st.status(f"Releasing in {p}...", expanded=False) as status:
                            proj_versions = get_versions_cached(config_tuple, p)
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
                    for p in current_selection:
                        with st.status(f"Archiving in {p}...", expanded=False) as status:
                            proj_versions = get_versions_cached(config_tuple, p)
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

if __name__ == "__main__":
    main()
