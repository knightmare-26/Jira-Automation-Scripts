import sys

JIRA_BASE_URL = "https://your-domain.atlassian.net"
JIRA_EMAIL = "your-email@example.com"
JIRA_API_TOKEN = "REDACTED_JIRA_TOKEN"

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    sys.exit("Missing env vars: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")

API_BASE = f"{JIRA_BASE_URL}/rest/api/3"
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}