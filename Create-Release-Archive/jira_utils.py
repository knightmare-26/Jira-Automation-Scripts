import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def clean_url(url):
    """Ensure the URL doesn't have double slashes except for the protocol."""
    if "://" in url:
        protocol, path = url.split("://", 1)
        return f"{protocol}://{path.replace('//', '/')}"
    return url.replace("//", "/")

def get_projects(config):
    """Fetch all available JIRA projects using provided config."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return []
    try:
        url = clean_url(f"{config['API_BASE']}/project")
        r = requests.get(url, auth=config['AUTH'], headers=config['HEADERS'])
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
        url = clean_url(f"{config['API_BASE']}/project/{project_key}/versions")
        r = requests.get(url, auth=config['AUTH'], headers=config['HEADERS'])
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
        url = clean_url(f"{config['API_BASE']}/version")
        r = requests.post(
            url,
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
        url = clean_url(f"{config['API_BASE']}/version/{version_id}")
        r = requests.get(url, auth=config['AUTH'], headers=config['HEADERS'])
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
        url = clean_url(f"{config['API_BASE']}/version/{version_id}")
        r = requests.put(
            url,
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
        url = clean_url(f"{config['API_BASE']}/version/{version_id}")
        r = requests.put(
            url,
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
    """Rename a version."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    try:
        url = clean_url(f"{config['API_BASE']}/version/{version_id}")
        r = requests.put(
            url,
            auth=config['AUTH'],
            headers=config['HEADERS'],
            json={
                "name": new_name
            },
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error renaming version {old_name} to {new_name} in project {project_key}: {e}")
        return False

def get_user_info(config):
    """Fetch current user info to test Jira API credentials."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return None
    try:
        # Jira API 3 endpoint to fetch self
        url = clean_url(f"{config['API_BASE']}/myself")
        r = requests.get(url, auth=config['AUTH'], headers=config['HEADERS'])
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error validating credentials: {e}")
        return None

def get_filters(config):
    """Fetch all editable filters for the current user."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return []
    
    filters = []
    start_at = 0
    max_results = 50
    
    while True:
        try:
            params = [
                ("expand", "jql"),
                ("expand", "editable"),
                ("startAt", start_at),
                ("maxResults", max_results)
            ]
            url = clean_url(f"{config['API_BASE']}/filter/search")
            r = requests.get(
                url, 
                auth=config['AUTH'], 
                headers=config['HEADERS'],
                params=params
            )
            r.raise_for_status()
            data = r.json()
            
            # Debug: Log total found and a sample of the first filter's flags
            all_values = data.get("values", [])
            logger.info(f"Fetched {len(all_values)} filters in this batch. Total in Jira: {data.get('total')}")
            if all_values:
                sample = all_values[0]
                logger.info(f"Sample Filter - Name: {sample.get('name')}, Editable: {sample.get('editable')}")

            # Filter for editable filters
            batch = [f for f in all_values if f.get("editable")]
            filters.extend(batch)
            
            if data.get("isLast", True) or not data.get("values"):
                break
            start_at += len(data.get("values", []))
        except Exception as e:
            logger.error(f"Error fetching filters: {e}")
            break
            
    return filters

def update_filter_jql(config, filter_id, new_jql):
    """Update the JQL of a specific filter."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return False
    
    try:
        url = clean_url(f"{config['API_BASE']}/filter/{filter_id}")
        r = requests.put(
            url,
            auth=config['AUTH'],
            headers=config['HEADERS'],
            json={"jql": new_jql}
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error updating filter {filter_id}: {e}")
        return False

def get_filter_by_name(config, filter_name):
    """Search for a filter by name and return its details if editable."""
    if not config or not config.get("API_BASE") or not config.get("AUTH"):
        return None
    
    try:
        params = [
            ("filterName", filter_name),
            ("expand", "jql,editable")
        ]
        url = clean_url(f"{config['API_BASE']}/filter/search")
        r = requests.get(
            url, 
            auth=config['AUTH'], 
            headers=config['HEADERS'],
            params=params
        )
        r.raise_for_status()
        data = r.json()
        
        for f in data.get("values", []):
            if f.get("name") == filter_name:
                return f
    except Exception as e:
        logger.error(f"Error finding filter '{filter_name}': {e}")
    
    return None
