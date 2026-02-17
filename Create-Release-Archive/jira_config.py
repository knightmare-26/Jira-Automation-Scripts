import os
import sys

# Read credentials from environment variables to avoid committing secrets.
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    sys.exit("Missing env vars: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")

API_BASE = f"{JIRA_BASE_URL}/rest/api/3"
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}