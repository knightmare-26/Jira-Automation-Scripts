import logging
import requests
from datetime import datetime, timezone
from jira_config import API_BASE, AUTH, HEADERS

# ======================
# EDIT THESE
PROJECTS = ["AL",
"TLS",
"ANDRO",
"CALC",
"CAS",
"CM",
"COS",
"PECP",
"EP",
"GLX",
"GEM",
"GRAV",
"CND",
"LYRA",
"NOVA",
"TITAN",
"VEGA",
"DPM",
"DWIZ"]
VERSIONS = ["2025TrainC1",
"2025Train1",
"2024Train4",
"2024Train5"]
# ======================


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Also log all runs/actions to a shared file
file_handler = logging.FileHandler("jira_automation_runs.log")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(file_handler)


def get_versions(project):
    logger.info("Fetching versions for project %s", project)
    r = requests.get(
        f"{API_BASE}/project/{project}/versions",
        auth=AUTH,
        headers=HEADERS,
    )
    r.raise_for_status()
    versions = r.json()
    logger.info("Fetched %d versions for project %s", len(versions), project)
    return versions


def release_version(version_id, project, version_name):
    logger.info("Releasing version %s in project %s", version_name, project)
    r = requests.put(
        f"{API_BASE}/version/{version_id}",
        auth=AUTH,
        headers=HEADERS,
        json={
            "released": True,
            "releaseDate": datetime.now(timezone.utc).date().isoformat(),
        },
    )
    r.raise_for_status()
    logger.info("Successfully released version %s in project %s", version_name, project)


def main():
    logger.info(
        "Starting release_versions run projects=%s versions=%s", PROJECTS, VERSIONS
    )
    for project in PROJECTS:
        for v in get_versions(project):
            if v["name"] in VERSIONS and not v.get("released"):
                logger.info("%s: releasing %s", project, v["name"])
                release_version(v["id"], project, v["name"])
    logger.info("Completed release_versions run")


if __name__ == "__main__":
    main()
