# Plan: Landing Page & Guest Mode Implementation

## Objective
Implement a professional landing page and a "Guest Mode" that allows users to use the tool without persistent storage, while providing clear guidance for first-time users.

## Key Changes

### 1. State Management & Navigation Flow
- **Views:** Introduce `st.session_state.view` to control the current screen: `'landing'`, `'login'`, or `'app'`.
- **Guest Mode:** Introduce `st.session_state.is_guest` (boolean) to toggle between local-only and cloud-persisted storage.
- **Routing:** Update `main()` to act as a router based on these states.

### 2. New Landing Page (`view: 'landing'`)
- **Title:** `🎯 Jira Version Manager`
- **Brief Overview:** Highlight the tool's purpose: batch managing fix versions across multiple projects with ease.
- **Features Highlight:**
    - Batch creation, release, archive, and renaming.
    - Custom project tracking and quick-access shortcuts.
- **Quick Start Instructions (3 Steps):**
    1.  **Configure:** Enter your Jira URL, Email, and API Token.
        - **Guidance:** Include a tooltip and direct link to [Create Jira API Token](https://id.atlassian.com/manage-profile/security/api-tokens) to assist new users.
    2.  **Select Projects:** Add projects to your tracking list and activate the ones you want to manage.
    3.  **Perform Actions:** Create or update versions across all active projects in one click.
- **Call to Action Buttons:**
    - `🚀 Try it now (Guest Mode)` -> Sets `is_guest=True`, `view='app'`, `username='Guest'`.
    - `🔐 Login or Sign Up` -> Sets `view='login'`.

### 3. Guest Mode Logic (`jira_ui.py`)
- **Data Isolation:** Update data functions to bypass Supabase when `st.session_state.is_guest` is `True`:
    - `load_managed_projects` / `save_managed_projects`: Use a dedicated `st.session_state.guest_projects` variable.
    - `load_jira_config` / `save_jira_config`: Store configuration only in `st.session_state.jira_config`.
    - `load_shortcuts` / `save_shortcuts`: Disabled for guests (display "Sign up to save shortcuts" message).
- **UI Adjustments:**
    - Sidebar: Display "Guest Mode (Session Only)" instead of the username.
    - Sidebar: Add a "Log in to save settings" button to encourage conversion.
    - Disable persistent features like "Save Selection as Shortcut" and "Manage Tracked Projects" (guests will see all projects directly from Jira).

### 5. Refactoring: Database Schema Migration
- **Objective:** Move from monolithic `app_config` storage to relational tables for better performance, concurrency, and maintainability.
- **New Tables:**
    - `profiles`: Core user identity.
    - `jira_credentials`: Encrypted tokens and Jira URLs.
    - `user_settings`: User-specific preferences.
    - `auth_system_config`: Global configuration.
- **Why:** 
    - Eliminates concurrency issues (User A vs. User B overwrites).
    - Enhances readability and query performance.
    - Simplifies Row-Level Security (RLS) implementation.


## Verification & Testing
- **Visual Audit:** Confirm the landing page layout and the Jira Token tooltip/link.
- **Guest Flow:**
    - Verify that configuring Jira works and project data is fetched.
    - Confirm that actions (Create/Release/Rename) execute correctly.
    - Ensure a browser refresh wipes all guest data (expected behavior).
- **Authenticated Flow:**
    - Ensure existing user login/registration still works perfectly.
    - Confirm that data persists across sessions for logged-in users.
- **Security Check:** Verify that no data from Guest Mode is written to Supabase tables.
