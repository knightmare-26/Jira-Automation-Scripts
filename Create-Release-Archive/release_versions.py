import logging
import jira_utils

# ======================
# EDIT THESE
PROJECTS = ["AL", "TLS", "ANDRO", "CALC", "CAS", "CM", "COS", "PECP", "EP", "GLX", "GEM", "GRAV", "CND", "LYRA", "NOVA", "TITAN", "VEGA", "DPM", "DWIZ", "PRODE"]
VERSIONS = ["2025TrainC1", "2025Train1", "2024Train4", "2024Train5"]
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

def main():
    logger.info(
        "Starting release_versions run projects=%s versions=%s", PROJECTS, VERSIONS
    )
    for project in PROJECTS:
        versions = jira_utils.get_versions(project)
        for v in versions:
            if v["name"] in VERSIONS and not v.get("released"):
                logger.info("%s: releasing %s", project, v["name"])
                if jira_utils.release_version(v["id"], project, v["name"]):
                    logger.info("Successfully released version %s in project %s", v["name"], project)
                else:
                    logger.error("Failed to release version %s in project %s", v["name"], project)
    logger.info("Completed release_versions run")

if __name__ == "__main__":
    main()
