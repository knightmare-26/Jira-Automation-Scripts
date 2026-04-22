import requests
import logging
from datetime import datetime, timezone
import jira_config

logger = logging.getLogger(__name__)

def get_projects():
    """Fetch all available JIRA projects."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return []
    try:
        r = requests.get(f"{jira_config.API_BASE}/project", auth=jira_config.AUTH, headers=jira_config.HEADERS)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return []

def get_versions(project_key):
    """Fetch all versions for a specific project."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return []
    try:
        r = requests.get(f"{jira_config.API_BASE}/project/{project_key}/versions", auth=jira_config.AUTH, headers=jira_config.HEADERS)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching versions for project {project_key}: {e}")
        return []

def get_all_fix_versions(project_keys=None):
    """Fetch fix versions for specific projects or all if none specified."""
    if project_keys:
        projects = [{"key": k} for k in project_keys]
    else:
        projects = get_projects()
        
    all_versions = []
    for project in projects:
        versions = get_versions(project['key'])
        for v in versions:
            v["projectKey"] = project["key"]
            all_versions.append(v)
    return all_versions

def create_version(project_key, version_name, start_date=None, release_date=None):
    """Create a new version in a project."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return False
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {jira_config.JIRA_EMAIL}" if jira_config.JIRA_EMAIL else ""
    description = f"Created{user_info} on {now_str}."
    
    payload = {
        "name": version_name, 
        "project": project_key,
        "description": description
    }
    
    if start_date:
        payload["startDate"] = start_date
    if release_date:
        payload["releaseDate"] = release_date

    try:
        r = requests.post(
            f"{jira_config.API_BASE}/version",
            auth=jira_config.AUTH,
            headers=jira_config.HEADERS,
            json=payload,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error creating version {version_name} in project {project_key}: {e}")
        return False

def get_version(version_id):
    """Fetch details for a specific version."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return None
    try:
        r = requests.get(f"{jira_config.API_BASE}/version/{version_id}", auth=jira_config.AUTH, headers=jira_config.HEADERS)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching version {version_id}: {e}")
        return None

def release_version(version_id, project_key, version_name):
    """Mark a version as released."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return False
    
    # Fetch existing version to preserve description
    existing_version = get_version(version_id)
    existing_desc = existing_version.get("description", "") if existing_version else ""
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {jira_config.JIRA_EMAIL}" if jira_config.JIRA_EMAIL else ""
    new_log = f"Released{user_info} on {now_str}."
    
    combined_desc = f"{existing_desc}\n{new_log}".strip()
    
    try:
        r = requests.put(
            f"{jira_config.API_BASE}/version/{version_id}",
            auth=jira_config.AUTH,
            headers=jira_config.HEADERS,
            json={
                "released": True,
                "releaseDate": datetime.now(timezone.utc).date().isoformat(),
                "description": combined_desc
            },
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error releasing version {version_name} in project {project_key}: {e}")
        return False

def archive_version(version_id, project_key, version_name):
    """Mark a version as archived."""
    if not jira_config.API_BASE or not jira_config.AUTH:
        return False
    
    # Fetch existing version to preserve description
    existing_version = get_version(version_id)
    existing_desc = existing_version.get("description", "") if existing_version else ""
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {jira_config.JIRA_EMAIL}" if jira_config.JIRA_EMAIL else ""
    new_log = f"Archived{user_info} on {now_str}."
    
    combined_desc = f"{existing_desc}\n{new_log}".strip()
    
    try:
        r = requests.put(
            f"{jira_config.API_BASE}/version/{version_id}",
            auth=jira_config.AUTH,
            headers=jira_config.HEADERS,
            json={
                "archived": True,
                "description": combined_desc
            },
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error archiving version {version_name} in project {project_key}: {e}")
        return False
