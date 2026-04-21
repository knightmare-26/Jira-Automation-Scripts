# Jira Version Manager

A simple tool to manage Jira fix versions across multiple projects at once.

## 👥 Sharing the Application
1. **Push to GitHub:** If you haven't already, push this project to your GitHub repository.
2. **Instructions for New Users:**
   - Go to your GitHub repository.
   - Click the green **"<> Code"** button and select **"Download ZIP"** (or clone it if they know Git).
   - Follow the **🚀 Easy Start** instructions below.

## 🚀 Easy Start (For Everyone)
No developer knowledge is required!
1. **Unzip** the folder you downloaded.
2. **Double-click** the file named `Run_Jira_Manager.command`.
   - *Note: If macOS prevents it from opening, Right-Click the file and select "Open".*
3. A terminal window will open and automatically set everything up for you. 
4. **Wait a few seconds**, and the manager will open in your web browser.
5. Go to the **⚙️ Config** page in the sidebar to enter your Jira details.

---

## 📂 Manage Projects
You can customize which projects appear in your UI:
1. Go to **📂 Manage Projects**.
2. Use the **"⚙️ Manage Tracked Projects"** tab to add any project from your Jira account or remove ones you don't need.
3. Use the **"🎯 Active Workspace"** tab to quickly select which of your tracked projects you want to work with right now.

## Security & Privacy
- **Local Storage:** All credentials and shortcuts are stored **only on your computer** in `jira_config_local.py` and `local_shortcuts.json`.
- **Git Protected:** These files are automatically ignored by Git to prevent accidental sharing.

---
**Note for the Sharer:** Before zipping this folder to send to others, please delete your local `jira_config_local.py` and `local_shortcuts.json` files so they don't include your private credentials!
