import sys

JIRA_BASE_URL = "https://aeratechnology.atlassian.net"
JIRA_EMAIL = "elijah.dsouza@aeratechnology.com"
JIRA_API_TOKEN = "ATATT3xFfGF03Z-8TatvRB-lV0U_o3yUy8s4dh4F_SUspTcWhK9h7Ro85lBY5r044cxHvTcItKiMOT69Lu6Pd_MXWrB28T_CY6ZHgJMiQA2G1XplO5_zjEWtobAEzbflqcubtQNfdbLPxSuv0RIcQcpFgzw7450fR9DG41pT0aHBTKnJ9lFUsHA=F4B93B0E"

if not all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
    sys.exit("Missing env vars: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")

API_BASE = f"{JIRA_BASE_URL}/rest/api/3"
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}