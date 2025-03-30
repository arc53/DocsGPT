import logging
import requests
from typing import Dict, Optional
from bson.objectid import ObjectId

from application.core.mongo_db import MongoDB

logger = logging.getLogger(__name__)

# Get MongoDB connection
mongo = MongoDB.get_client()
db = mongo["docsgpt"]
proxies_collection = db["proxies"]

def get_proxy_config(proxy_id: str) -> Optional[Dict[str, str]]:
    """
    Retrieve proxy configuration from the database.
    
    Args:
        proxy_id: The ID of the proxy configuration
        
    Returns:
        A dictionary with proxy configuration or None if not found
    """
    if not proxy_id or proxy_id == "none":
        return None
        
    try:
        if ObjectId.is_valid(proxy_id):
            proxy_config = proxies_collection.find_one({"_id": ObjectId(proxy_id)})
            if proxy_config and "connection" in proxy_config:
                connection_str = proxy_config["connection"].strip()
                if connection_str:
                    # Format proxy for requests library
                    return {
                        "http": connection_str,
                        "https": connection_str
                    }
        return None
    except Exception as e:
        logger.error(f"Error retrieving proxy configuration: {e}")
        return None

def apply_proxy_to_request(request_func, proxy_id=None, **kwargs):
    """
    Apply proxy configuration to a requests function if available.
    This is a minimal wrapper that doesn't change the function signature.
    
    Args:
        request_func: The requests function to call (e.g., requests.get, requests.post)
        proxy_id: Optional proxy ID to use
        **kwargs: Arguments to pass to the request function
    
    Returns:
        The response from the request
    """
    if proxy_id:
        proxy_config = get_proxy_config(proxy_id)
        if proxy_config:
            kwargs['proxies'] = proxy_config
            logger.info(f"Using proxy for request")
    
    return request_func(**kwargs)