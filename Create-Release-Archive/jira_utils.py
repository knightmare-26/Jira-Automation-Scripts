import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def get_projects(config):
    """Fetch all available JIRA projects using provided config."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return []
    try:
        r = requests.get(f"{config['API_BASE']}/project", auth=config['AUTH'], headers=config['HEADERS'])
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return []

def get_versions(config, project_key):
    """Fetch all versions for a specific project."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return []
    try:
        r = requests.get(f"{config['API_BASE']}/project/{project_key}/versions", auth=config['AUTH'], headers=config['HEADERS'])
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching versions for project {project_key}: {e}")
        return []

def create_version(config, project_key, version_name, start_date=None, release_date=None):
    """Create a new version in a project."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {config.get('JIRA_EMAIL')}" if config.get('JIRA_EMAIL') else ""
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
            f"{config['API_BASE']}/version",
            auth=config['AUTH'],
            headers=config['HEADERS'],
            json=payload,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error creating version {version_name} in project {project_key}: {e}")
        return False

def get_version(config, version_id):
    """Fetch details for a specific version."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return None
    try:
        r = requests.get(f"{config['API_BASE']}/version/{version_id}", auth=config['AUTH'], headers=config['HEADERS'])
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching version {version_id}: {e}")
        return None

def release_version(config, version_id, project_key, version_name):
    """Mark a version as released."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    # Fetch existing version to preserve description
    existing_version = get_version(config, version_id)
    existing_desc = existing_version.get("description", "") if existing_version else ""
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {config.get('JIRA_EMAIL')}" if config.get('JIRA_EMAIL') else ""
    new_log = f"Released{user_info} on {now_str}."
    
    combined_desc = f"{existing_desc}\n{new_log}".strip()
    
    try:
        r = requests.put(
            f"{config['API_BASE']}/version/{version_id}",
            auth=config['AUTH'],
            headers=config['HEADERS'],
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

def archive_version(config, version_id, project_key, version_name):
    """Mark a version as archived."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    # Fetch existing version to preserve description
    existing_version = get_version(config, version_id)
    existing_desc = existing_version.get("description", "") if existing_version else ""
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {config.get('JIRA_EMAIL')}" if config.get('JIRA_EMAIL') else ""
    new_log = f"Archived{user_info} on {now_str}."
    
    combined_desc = f"{existing_desc}\n{new_log}".strip()
    
    try:
        r = requests.put(
            f"{config['API_BASE']}/version/{version_id}",
            auth=config['AUTH'],
            headers=config['HEADERS'],
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

def rename_version(config, version_id, project_key, old_name, new_name):
    """Update the name of a Jira fix version."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    # Fetch existing version to preserve/update description
    existing_version = get_version(config, version_id)
    existing_desc = existing_version.get("description", "") if existing_version else ""
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_info = f" by {config.get('JIRA_EMAIL')}" if config.get('JIRA_EMAIL') else ""
    new_log = f"Renamed from '{old_name}' to '{new_name}'{user_info} on {now_str}."
    
    combined_desc = f"{existing_desc}\n{new_log}".strip()
    
    try:
        r = requests.put(
            f"{config['API_BASE']}/version/{version_id}",
            auth=config['AUTH'],
            headers=config['HEADERS'],
            json={
                "name": new_name,
                "description": combined_desc
            },
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error renaming version '{old_name}' to '{new_name}' in project {project_key}: {e}")
        return False
