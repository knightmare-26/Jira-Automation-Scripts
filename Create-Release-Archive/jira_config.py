# JIRA API Configuration Module
# ------------------------------
# This module manages authentication and API endpoints for JIRA automation scripts.
# Requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN to be defined.

# Required Configuration Variables
# These are typically populated from Supabase via jira_ui.py
JIRA_BASE_URL = None
JIRA_EMAIL = None
JIRA_API_TOKEN = None

# API Construction
API_BASE = f"{JIRA_BASE_URL}/rest/api/3" if JIRA_BASE_URL else None
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN) if JIRA_EMAIL and JIRA_API_TOKEN else None

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
