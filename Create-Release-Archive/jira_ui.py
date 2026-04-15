import streamlit as st
import pandas as pd
import jira_utils
import jira_config
import os
import logging
import json

# Import the predefined projects list
try:
    from release_versions import PROJECTS as DEV_PROJECTS
except ImportError:
    DEV_PROJECTS = []

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

# UI Constants
PAGE_TITLE = "Jira Version Manager"
st.set_page_config(page_title=PAGE_TITLE, layout="wide", initial_sidebar_state="expanded")

SHORTCUTS_FILE = "local_shortcuts.json"

def load_shortcuts():
    default_shortcuts = {"Dev Projects": {"projects": DEV_PROJECTS, "versions": []}}
    if os.path.exists(SHORTCUTS_FILE):
        try:
            with open(SHORTCUTS_FILE, "r") as f:
                data = json.load(f)
                if "Dev Projects" not in data:
                    data["Dev Projects"] = default_shortcuts["Dev Projects"]
                return data
        except Exception as e:
            logger.error(f"Error loading shortcuts: {e}")
            return default_shortcuts
    return default_shortcuts

def save_shortcut(name, projects, versions):
    shortcuts = load_shortcuts()
    shortcuts[name] = {"projects": projects, "versions": versions}
    try:
        with open(SHORTCUTS_FILE, "w") as f:
            json.dump(shortcuts, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving shortcut: {e}")
        return False

def delete_shortcut(name):
    if name == "Dev Projects":
        return False
    shortcuts = load_shortcuts()
    if name in shortcuts:
        del shortcuts[name]
        with open(SHORTCUTS_FILE, "w") as f:
            json.dump(shortcuts, f, indent=4)
        return True
    return False

@st.cache_data(ttl=3600)
def get_all_projects_cached():
    projects = jira_utils.get_projects()
    if not projects:
        return []
    if DEV_PROJECTS:
        projects = [p for p in projects if p.get('key') in DEV_PROJECTS]
    return sorted(projects, key=lambda x: x.get('key', ''))

@st.cache_data(ttl=600)
def get_versions_cached(project_key):
    return jira_utils.get_versions(project_key)

def get_versions_for_projects_cached(project_keys):
    if not project_keys:
        return []
    all_version_names = set()
    for key in project_keys:
        versions = get_versions_cached(key)
        for v in versions:
            all_version_names.add(v.get('name'))
    return sorted(list(all_version_names))

def save_config(url, email, token):
    config_content = f"""JIRA_BASE_URL = "{url}"
JIRA_EMAIL = "{email}"
JIRA_API_TOKEN = "{token}"
"""
    with open("jira_config_local.py", "w") as f:
        f.write(config_content)
    st.success("Configuration saved! Re-loading...")

def main():
    # --- Shared Data ---
    all_projects = get_all_projects_cached()
    project_keys = [p['key'] for p in all_projects]

    # Initialize session state for selections
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "📂 Manage Projects"
    if 'selected_projects' not in st.session_state:
        st.session_state.selected_projects = set()
        for k in project_keys:
            st.session_state[f"cb_{k}"] = False
    if 'selected_versions' not in st.session_state:
        st.session_state.selected_versions = []

    # --- Sidebar Navigation & Shortcuts ---
    st.sidebar.title("🎯 Jira Manager")
    nav_options = ["📂 Manage Projects", "🚀 Create Versions", "📦 Release/Archive", "⚙️ Config"]
    
    # Use index to control the radio button programmatically
    try:
        current_index = nav_options.index(st.session_state.current_page)
    except ValueError:
        current_index = 0

    page = st.sidebar.radio("Navigation", options=nav_options, index=current_index, key="nav_widget")
    
    # Sync session state if user clicks the radio button directly
    if page != st.session_state.current_page:
        st.session_state.current_page = page
        st.rerun()

    st.sidebar.divider()
    st.sidebar.header("Quick Shortcuts")
    shortcuts = load_shortcuts()
    for name, data in shortcuts.items():
        col1, col2 = st.sidebar.columns([4, 1])
        if col1.button(f"📍 {name}", key=f"apply_{name}", use_container_width=True):
            new_proj_list = data.get("projects", [])
            st.session_state.selected_projects = set(new_proj_list)
            st.session_state.selected_versions = data.get("versions", [])
            # Sync individual checkbox states in session_state
            for k in project_keys:
                st.session_state[f"cb_{k}"] = k in st.session_state.selected_projects
            # Stay on current page or go to dashboard? Dashboard is safer for new selections
            st.session_state.current_page = "📂 Manage Projects"
            st.rerun()
        if name != "Dev Projects":
            if col2.button("🗑️", key=f"del_{name}"):
                if delete_shortcut(name):
                    st.rerun()

    # --- Page Content ---
    if page == "⚙️ Config":
        st.title("⚙️ Jira Configuration")
        st.info("Update your Jira connection details here.")
        url = st.text_input("Jira Base URL", value=jira_config.JIRA_BASE_URL or "")
        email = st.text_input("Jira Email", value=jira_config.JIRA_EMAIL or "")
        token = st.text_input("Jira API Token", value=jira_config.JIRA_API_TOKEN or "", type="password")
        if st.button("Save Configuration", type="primary"):
            save_config(url, email, token)
            st.rerun()

    elif page == "📂 Manage Projects":
        st.title("📂 Manage Projects")
        
        # Project Selection Section
        st.header("📂 Manage Projects")
        st.info("Select projects to define your active workspace.")
        
        col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 4])
        if col_ctrl1.button("Select All Projects", use_container_width=True):
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
        if all_projects:
            cols = st.columns(4)
            for idx, p in enumerate(all_projects):
                with cols[idx % 4]:
                    p_key = p['key']
                    
                    # Define a callback for the checkbox to update session state immediately
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

        st.divider()
        current_selection = list(st.session_state.selected_projects)
        if current_selection:
            st.success(f"✅ **{len(current_selection)} Projects Active:** {', '.join(sorted(current_selection))}")
            
            with st.expander("💾 Save Current Selection as Shortcut"):
                shortcut_name = st.text_input("Shortcut Name")
                if st.button("Save Shortcut"):
                    if shortcut_name:
                        if save_shortcut(shortcut_name, current_selection, st.session_state.selected_versions):
                            st.success(f"Saved shortcut: {shortcut_name}")
                            st.rerun()
                    else:
                        st.error("Please provide a name for the shortcut.")
        else:
            st.warning("⚠️ No projects selected. Please select projects to begin.")

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

            if final_versions:
                st.write(f"**Planned Versions:** {', '.join(final_versions)}")
                st.session_state.selected_versions = final_versions

            st.header("2. Execution")
            if st.button("🚀 Create Versions Across Active Projects", use_container_width=True, type="primary"):
                if not final_versions:
                    st.error("Please define at least one version name.")
                else:
                    for p in current_selection:
                        with st.status(f"Processing {p}...", expanded=True) as status:
                            existing_versions_list = get_versions_cached(p)
                            existing_names = {v["name"] for v in existing_versions_list}
                            for v in final_versions:
                                if v in existing_names:
                                    st.info(f"{p}: {v} already exists.")
                                else:
                                    if jira_utils.create_version(p, v):
                                        st.success(f"{p}: Created {v}")
                                        st.cache_data.clear()
                                    else:
                                        st.error(f"{p}: Failed to create {v}")
                            status.update(label=f"Finished {p}", state="complete")

    elif page == "📦 Release/Archive":
        st.title("📦 Release & Archive Versions")
        current_selection = sorted(list(st.session_state.selected_projects))
        
        if not current_selection:
            st.warning("⚠️ No projects selected. Please go to the **Manage Projects** page to select projects.")
        else:
            st.write(f"**Active Workspace:** {', '.join(current_selection)}")

            st.header("1. Select Target Versions")
            with st.spinner("Loading versions..."):
                available_versions = get_versions_for_projects_cached(current_selection)
            
            if not available_versions:
                st.info("No versions found for the selected projects.")
                target_versions = []
            else:
                valid_defaults = [v for v in st.session_state.selected_versions if v in available_versions]
                target_versions = st.multiselect(
                    "Select Versions to Modify",
                    options=available_versions,
                    default=valid_defaults
                )
            
            st.session_state.selected_versions = target_versions

            if target_versions:
                st.divider()
                st.header("2. Actions")
                st.write(f"Targeting: **{', '.join(target_versions)}**")
                st.warning("These actions will be applied to all selected versions across all active projects.")
                
                rel_col, arc_col = st.columns(2)
                
                if rel_col.button("✅ Release Versions", use_container_width=True, type="primary"):
                    for p in current_selection:
                        with st.status(f"Releasing in {p}...", expanded=False) as status:
                            proj_versions = get_versions_cached(p)
                            for v_name in target_versions:
                                target = next((v for v in proj_versions if v["name"] == v_name), None)
                                if target:
                                    if target.get("released"):
                                        st.info(f"{p}: {v_name} is already released.")
                                    else:
                                        if jira_utils.release_version(target["id"], p, v_name):
                                            st.success(f"{p}: Released {v_name}")
                                            st.cache_data.clear()
                                        else:
                                            st.error(f"{p}: Failed to release {v_name}")
                                else:
                                    st.warning(f"{p}: Version {v_name} not found.")
                            status.update(label=f"Completed {p}", state="complete")

                if arc_col.button("📦 Archive Versions", use_container_width=True):
                    for p in current_selection:
                        with st.status(f"Archiving in {p}...", expanded=False) as status:
                            proj_versions = get_versions_cached(p)
                            for v_name in target_versions:
                                target = next((v for v in proj_versions if v["name"] == v_name), None)
                                if target:
                                    if target.get("archived"):
                                        st.info(f"{p}: {v_name} is already archived.")
                                    else:
                                        if jira_utils.archive_version(target["id"], p, v_name):
                                            st.success(f"{p}: Archived {v_name}")
                                            st.cache_data.clear()
                                        else:
                                            st.error(f"{p}: Failed to archive {v_name}")
                                else:
                                    st.warning(f"{p}: Version {v_name} not found.")
                            status.update(label=f"Completed {p}", state="complete")

if __name__ == "__main__":
    main()
