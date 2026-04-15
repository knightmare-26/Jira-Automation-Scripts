# Jira Version Manager

A simple tool to manage Jira fix versions across multiple projects at once.

## 🚀 Easy Start (For Everyone)
If you just want to run the tool:
1. **Unzip** the folder.
2. **Double-click** the file named `Run_Jira_Manager.command`.
   - *Note: If macOS prevents it from opening, Right-Click the file and select "Open".*
3. A terminal window will open and automatically set everything up. 
4. **Wait a few seconds**, and the manager will open in your web browser.
5. Go to the **⚙️ Config** page in the sidebar to enter your Jira details.

---

## 🛠️ For Technical Users
### Prerequisites
- Python 3.9+
- Jira API Token (https://id.atlassian.com/manage-profile/security/api-tokens)

### Installation & Manual Run
```bash
pip install -r requirements.txt
streamlit run jira_ui.py
```

## Features
- **📂 Manage Projects:** Select which projects to target using the checkbox grid.
- **🚀 Create Versions:** Quickly create new versions across all selected projects.
- **📦 Release/Archive:** Batch update existing versions.
- **📍 Quick Shortcuts:** Save your project sets and version names for one-click access.

## Security & Privacy
- **Local Storage:** All credentials and shortcuts are stored **only on your computer** in `jira_config_local.py` and `local_shortcuts.json`.
- **Git Protected:** These files are automatically ignored by Git to prevent accidental sharing.

---
**Note for the Sharer:** Before zipping this folder to send to colleagues, please delete your local `jira_config_local.py` and `local_shortcuts.json` files so they don't include your private credentials!
