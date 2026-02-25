import requests
from jira_config import API_BASE, AUTH

projects = requests.get(
    f"{API_BASE}/project",
    auth=AUTH
).json()

all_versions = []

for project in projects:
    versions = requests.get(
        f"{API_BASE}/project/{project['key']}/versions",
        auth=AUTH
    ).json()
    for v in versions:
        v["projectKey"] = project["key"]
        all_versions.append(v)

print(all_versions)