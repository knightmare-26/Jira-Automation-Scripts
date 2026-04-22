# JIRA API Configuration Module
# ------------------------------
# This module manages authentication and API endpoints for JIRA automation scripts.
# Requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN to be defined.

import sys

# Required Configuration Variables
# Replace these with your JIRA instance details
JIRA_BASE_URL = None  # e.g., "https://your-domain.atlassian.net"
JIRA_EMAIL = None     # e.g., "name@company.com"
JIRA_API_TOKEN = None # Generate at https://id.atlassian.com/manage-profile/security/api-tokens

try:
    # Attempt to load configuration overrides from a local file
    from . import jira_config_local
    JIRA_BASE_URL = getattr(jira_config_local, "JIRA_BASE_URL", JIRA_BASE_URL)
    JIRA_EMAIL = getattr(jira_config_local, "JIRA_EMAIL", JIRA_EMAIL)
    JIRA_API_TOKEN = getattr(jira_config_local, "JIRA_API_TOKEN", JIRA_API_TOKEN)
except (ImportError, ValueError):
    try:
        import jira_config_local
        JIRA_BASE_URL = getattr(jira_config_local, "JIRA_BASE_URL", JIRA_BASE_URL)
        JIRA_EMAIL = getattr(jira_config_local, "JIRA_EMAIL", JIRA_EMAIL)
        JIRA_API_TOKEN = getattr(jira_config_local, "JIRA_API_TOKEN", JIRA_API_TOKEN)
    except ImportError:
        pass

# API Construction
API_BASE = f"{JIRA_BASE_URL}/rest/api/3" if JIRA_BASE_URL else None
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN) if JIRA_EMAIL and JIRA_API_TOKEN else None

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    print("Error: JIRA configuration is incomplete. Please ensure all variables are set.")
