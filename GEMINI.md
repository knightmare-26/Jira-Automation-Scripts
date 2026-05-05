# Gemini CLI - Project Progress & Architecture

## 📋 Overview
This project is a Streamlit-based Jira Version Manager. It allows for batch project tracking, version creation, releasing, archiving, and renaming across multiple Jira projects with multi-user support and Supabase cloud persistence.

---

## 🛠 Development Phases (UI/UX & Features)

### Phase 1: Navigation Consolidation (Completed)
- Streamlined sidebar into three core sections: `📂 Manage Projects`, `🚀 Manage Versions`, and `⚙️ Config`.
- Implemented tab-based navigation within pages to reduce vertical scrolling and clutter.

### Phase 2: Feature Expansion (Completed)
- **Batch Renaming:** Added the ability to rename fix versions across multiple projects simultaneously.
- **Improved Shortcuts:** Moved shortcut creation to a prominent `+` button in the sidebar with vertical centering and high-contrast styling.
- **Conditional Actions:** Buttons for version actions (Create, Release, Rename) now only appear when relevant inputs/selections are provided.

### Phase 3: UX & Session Management (Completed)
- **Refresh Persistence:** Fixed the issue where users were logged out on browser refresh.
- **Session Cleanup:** Implemented logic to reset `selected_projects` and checkboxes on logout or user switch.
- **Simplified Auth:** Streamlined the registration form to Username, Email, and Password (hiding unnecessary fields via CSS).

---

## 🔒 Security Phases (Audit & Remediation)

### Phase 1: Data Encryption (Completed)
- **Risk:** Jira API Tokens stored in plaintext in Supabase.
- **Fix:** Implemented Fernet (AES-128) encryption. Tokens are encrypted before storage and decrypted on-the-fly.
- **Migration:** Automated backward compatibility layer that encrypts old plaintext tokens upon first access.

### Phase 2: Session & Cache Isolation (Completed)
- **Risk:** Streamlit's `@st.cache_data` was global, potentially leaking project data between users.
- **Fix:** Scoped all cached Jira API calls by `username`, ensuring strict data isolation per session.

### Phase 3: Granular Persistence (Completed)
- **Risk:** Monolithic `users_config` record caused concurrency issues (User A overwriting User B).
- **Fix:** Refactored auth storage to use granular records (`auth_user_{username}`).
- **Migration:** Implemented automated sync logic to split old monolithic files into individual records.

### Phase 4: Hardening & Logging (Completed)
- **Risk:** Sensitive data leakage in log files or error stack traces.
- **Fix:** Added `sanitize_data` utility to redact tokens/passwords from logs. Replaced raw error logging with `safe_log_error` wrappers.

---

## 🚀 Future Roadmap & Pending Steps
1. **Supabase RLS:** (Completed ✅) Row Level Security has been enabled on `app_config` to enforce database-level data isolation.
2. **Supabase Native Auth:** Potential migration from `streamlit-authenticator` to native Supabase JWT auth for improved security.
3. **Advanced Permissions:** Role-based access control for different team members.
4. **Relational Database Migration:** Migrate from monolithic `app_config` (JSON blobs) to relational tables (`profiles`, `jira_credentials`, `user_settings`) to improve performance, data isolation, and eliminate concurrency issues.

---
*Last Updated: April 29, 2026*
