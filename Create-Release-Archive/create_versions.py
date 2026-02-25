import logging
import requests
from jira_config import API_BASE, AUTH, HEADERS

# ======================
# EDIT THESE
PROJECTS = ["ABC"]
VERSIONS = ["2026Train123"]
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
    versions = {v["name"] for v in r.json()}
    logger.info("Fetched %d existing versions for project %s", len(versions), project)
    return versions

def create_version(project, version):
    logger.info("Creating version %s in project %s", version, project)
    r = requests.post(
        f"{API_BASE}/version",
        auth=AUTH,
        headers=HEADERS,
        json={"name": version, "project": project},
    )
    r.raise_for_status()
    logger.info("Successfully created version %s in project %s", version, project)

def main():
    logger.info(
        "Starting create_versions run projects=%s versions=%s", PROJECTS, VERSIONS
    )
    for project in PROJECTS:
        existing = get_versions(project)

        for version in VERSIONS:
            if version in existing:
                logger.info(
                    "%s: version %s already exists; skipping create", project, version
                )
                continue

            logger.info("%s: creating version %s", project, version)
            create_version(project, version)

    logger.info("Completed create_versions run")

if __name__ == "__main__":
    main()
