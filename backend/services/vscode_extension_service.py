"""
VSCode/Cursor Extension Service

This service provides functionality to:
- Fetch extensions from VSCode Marketplace API
- Search and filter extensions
- Check compatibility with the current system
- Handle extension metadata and installation info
"""

import aiohttp
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import os

logger = logging.getLogger(__name__)

# Use Open VSX Registry API (open-source alternative to VSCode Marketplace)
# This is more reliable and doesn't require complex authentication
VSCODE_MARKETPLACE_API = "https://open-vsx.org/api/-/search"
VSCODE_MARKETPLACE_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Fallback to VSCode Marketplace if needed (but it's more restrictive)
VSCODE_MARKETPLACE_API_FALLBACK = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
VSCODE_MARKETPLACE_HEADERS_FALLBACK = {
    "Accept": "application/json;api-version=3.0-preview.1",
    "Content-Type": "application/json"
}

# Extension categories mapping
VSCODE_CATEGORIES = {
    "themes": "Themes",
    "icon_themes": "Icon Themes",
    "languages": "Languages",
    "grammars": "Grammars",
    "language_servers": "Language Servers",
    "snippets": "Snippets",
    "debuggers": "Debuggers",
    "formatters": "Formatters",
    "linters": "Linters",
    "other": "Other"
}


class VSCodeExtensionService:
    """Service for fetching and managing VSCode/Cursor extensions"""
    
    def __init__(self):
        self.cache_dir = Path(os.getenv("AI_AGENT_CONFIG_DIR", os.path.expanduser("~/.ai_agent"))) / "extensions_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = 3600  # 1 hour cache
    
    async def search_extensions(
        self,
        query: str = "",
        category: str = "all",
        page_size: int = 50,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """
        Search for extensions using Open VSX Registry API
        
        Args:
            query: Search query string
            category: Extension category filter
            page_size: Number of results per page
            page_number: Page number (1-indexed)
            
        Returns:
            Dictionary with extensions list and metadata
        """
        try:
            # Build query parameters for Open VSX API
            params = {
                "size": page_size,
                "offset": (page_number - 1) * page_size,
                "sortBy": "relevance"  # relevance, downloadCount, averageRating, timestamp
            }
            
            # Add search query
            if query:
                params["query"] = query
            
            # Add category filter using tags
            if category and category != "all":
                tag = self._get_category_tag(category)
                if tag:
                    if "query" in params:
                        params["query"] = f"{params['query']} tag:{tag}"
                    else:
                        params["query"] = f"tag:{tag}"
            
            # Make API request to Open VSX
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    VSCODE_MARKETPLACE_API,
                    headers=VSCODE_MARKETPLACE_HEADERS,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Open VSX API returned status {response.status}: {error_text}")
                        return {"extensions": [], "total": 0, "error": f"API returned status {response.status}: {error_text[:200]}"}
                    
                    data = await response.json()
                    
                    # Parse Open VSX response format
                    extensions = []
                    extensions_data = data.get("extensions", [])
                    
                    for ext in extensions_data:
                        parsed = self._parse_openvsx_extension(ext)
                        if parsed:
                            extensions.append(parsed)
                    
                    total_count = data.get("totalSize", len(extensions))
                    
                    return {
                        "extensions": extensions,
                        "total": total_count,
                        "page_number": page_number,
                        "page_size": page_size
                    }
        
        except Exception as e:
            logger.error(f"Error searching VSCode extensions: {e}", exc_info=True)
            return {"extensions": [], "total": 0, "error": str(e)}
    
    def _get_category_tag(self, category: str) -> Optional[str]:
        """Get Open VSX tag for a category"""
        category_tag_map = {
            "themes": "theme",
            "icon_themes": "icon-theme",
            "languages": "programming-language",
            "grammars": "grammar",
            "language_servers": "language-server",
            "snippets": "snippet",
            "debuggers": "debugger",
            "formatters": "formatter",
            "linters": "linter",
        }
        return category_tag_map.get(category)
    
    def _parse_openvsx_extension(self, ext_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Open VSX extension data into our format"""
        try:
            # Get extension identifier
            namespace = ext_data.get("namespace", "")
            name = ext_data.get("name", "")
            extension_id = f"{namespace}.{name}"
            
            # Get latest version
            all_versions = ext_data.get("allVersions", [])
            latest_version = ext_data.get("version", "")
            
            # Get display name and description
            display_name = ext_data.get("displayName", name)
            description = ext_data.get("description", "")
            
            # Get categories/tags
            tags = ext_data.get("tags", [])
            category = self._determine_category(tags)
            
            # Get statistics
            download_count = ext_data.get("downloadCount", 0)
            review_count = ext_data.get("reviewCount", 0)
            average_rating = ext_data.get("averageRating", 0)
            
            # Get publisher info
            publisher = ext_data.get("namespace", "")
            
            # Get icon and other assets
            icon_url = ext_data.get("iconUrl", "")
            
            # Get repository URL
            repository_url = ext_data.get("repository", "")
            homepage_url = ext_data.get("homepage", "")
            
            # Get marketplace URL
            marketplace_url = f"https://open-vsx.org/extension/{namespace}/{name}"
            
            # Check compatibility
            is_compatible = self._check_compatibility_openvsx(ext_data)
            
            return {
                "id": extension_id,
                "name": display_name,
                "publisher": publisher,
                "publisher_id": namespace,
                "version": latest_version,
                "description": description,
                "category": category,
                "tags": tags,
                "downloads": download_count,
                "icon_url": icon_url,
                "repository_url": repository_url or homepage_url,
                "marketplace_url": marketplace_url,
                "is_compatible": is_compatible,
                "extension_type": "vscode",
                "vsix_url": f"https://open-vsx.org/api/{namespace}/{name}/{latest_version}/file/{namespace}.{name}-{latest_version}.vsix",
                "last_updated": ext_data.get("timestamp", ""),
                "published_date": ext_data.get("timestamp", ""),
                "average_rating": average_rating,
                "review_count": review_count
            }
        except Exception as e:
            logger.error(f"Error parsing Open VSX extension: {e}", exc_info=True)
            return None
    
    def _parse_extension(self, ext_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse VSCode extension data into our format"""
        try:
            # Get extension identifier
            publisher = ext_data.get("publisher", {}).get("publisherName", "")
            extension_name = ext_data.get("extensionName", "")
            extension_id = f"{publisher}.{extension_name}"
            
            # Get latest version
            versions = ext_data.get("versions", [])
            if not versions:
                return None
            
            latest_version = versions[0]
            
            # Get display name and description
            display_name = latest_version.get("displayName", extension_name)
            description = latest_version.get("shortDescription", "")
            
            # Get categories/tags
            tags = latest_version.get("tags", [])
            category = self._determine_category(tags)
            
            # Get statistics
            statistics = ext_data.get("statistics", [])
            downloads = 0
            for stat in statistics:
                if stat.get("statisticName") == "install":
                    downloads = stat.get("value", 0)
                    break
            
            # Get publisher info
            publisher_display_name = ext_data.get("publisher", {}).get("displayName", publisher)
            
            # Get icon and other assets
            assets = latest_version.get("assets", {})
            icon_url = None
            for asset in assets.get("icons", []):
                if asset.get("assetType") == "Microsoft.VisualStudio.Services.Icons.Default":
                    icon_url = asset.get("source")
                    break
            
            # Get repository URL
            properties = latest_version.get("properties", [])
            repository_url = None
            for prop in properties:
                if prop.get("key") == "Microsoft.VisualStudio.Services.Links.Source":
                    repository_url = prop.get("value")
                    break
            
            # Check compatibility
            is_compatible = self._check_compatibility(latest_version)
            
            return {
                "id": extension_id,
                "name": display_name,
                "publisher": publisher_display_name,
                "publisher_id": publisher,
                "version": latest_version.get("version", "0.0.0"),
                "description": description,
                "category": category,
                "tags": tags,
                "downloads": downloads,
                "icon_url": icon_url,
                "repository_url": repository_url,
                "marketplace_url": f"https://marketplace.visualstudio.com/items?itemName={extension_id}",
                "is_compatible": is_compatible,
                "extension_type": "vscode",
                "vsix_url": self._get_vsix_url(extension_id, latest_version.get("version")),
                "last_updated": latest_version.get("lastUpdated", ""),
                "published_date": latest_version.get("publishedDate", "")
            }
        except Exception as e:
            logger.error(f"Error parsing extension: {e}", exc_info=True)
            return None
    
    def _determine_category(self, tags: List[str]) -> str:
        """Determine extension category from tags"""
        tag_lower = [t.lower() for t in tags]
        
        if any(t in tag_lower for t in ["theme", "color-theme", "icon-theme"]):
            if "icon" in " ".join(tag_lower):
                return "Icon Themes"
            return "Themes"
        elif any(t in tag_lower for t in ["language", "programming-language"]):
            return "Languages"
        elif any(t in tag_lower for t in ["grammar", "textmate"]):
            return "Grammars"
        elif any(t in tag_lower for t in ["lsp", "language-server", "language-server-protocol"]):
            return "Language Servers"
        elif any(t in tag_lower for t in ["snippet", "snippets"]):
            return "Snippets"
        elif any(t in tag_lower for t in ["debugger", "debug"]):
            return "Debuggers"
        elif any(t in tag_lower for t in ["formatter", "format"]):
            return "Formatters"
        elif any(t in tag_lower for t in ["linter", "lint"]):
            return "Linters"
        else:
            return "Other"
    
    def _check_compatibility_openvsx(self, ext_data: Dict[str, Any]) -> bool:
        """Check if Open VSX extension is compatible with our system"""
        try:
            # Check engine requirements
            engines = ext_data.get("engines", {})
            vscode_version = engines.get("vscode", "")
            
            # Most extensions are compatible if they don't require specific engine versions
            # or if they require common versions
            if vscode_version:
                # Check if it requires a reasonable engine version
                # VSCode 1.0+ should be compatible
                try:
                    # Remove ^ or ~ prefix if present
                    version_str = vscode_version.replace("^", "").replace("~", "").split(".")[0]
                    major_version = int(version_str)
                    if major_version > 2:  # Very new versions might have issues
                        return False
                except:
                    pass
            
            # Check for unsupported features
            tags = ext_data.get("tags", [])
            tag_lower = [t.lower() for t in tags]
            
            # Some extension types might not work in our environment
            unsupported_tags = ["native", "native-module", "electron-specific"]
            if any(t in tag_lower for t in unsupported_tags):
                return False
            
            return True
        except Exception as e:
            logger.warning(f"Error checking compatibility: {e}")
            return True  # Default to compatible if check fails
    
    def _check_compatibility(self, version_data: Dict[str, Any]) -> bool:
        """Check if extension is compatible with our system"""
        try:
            # Check engine requirements
            properties = version_data.get("properties", [])
            engine_version = None
            for prop in properties:
                if prop.get("key") == "Microsoft.VisualStudio.Code.Engine":
                    engine_version = prop.get("value")
                    break
            
            # Most extensions are compatible if they don't require specific engine versions
            # or if they require common versions
            if engine_version:
                # Check if it requires a reasonable engine version
                # VSCode 1.0+ should be compatible
                try:
                    major_version = int(engine_version.split(".")[0])
                    if major_version > 2:  # Very new versions might have issues
                        return False
                except:
                    pass
            
            # Check for unsupported features
            tags = version_data.get("tags", [])
            tag_lower = [t.lower() for t in tags]
            
            # Some extension types might not work in our environment
            unsupported_tags = ["native", "native-module", "electron-specific"]
            if any(t in tag_lower for t in unsupported_tags):
                return False
            
            return True
        except Exception as e:
            logger.warning(f"Error checking compatibility: {e}")
            return True  # Default to compatible if check fails
    
    def _get_vsix_url(self, extension_id: str, version: str) -> Optional[str]:
        """Get VSIX download URL for extension from Open VSX"""
        try:
            namespace, name = extension_id.split(".", 1)
            return f"https://open-vsx.org/api/{namespace}/{name}/{version}/file/{namespace}.{name}-{version}.vsix"
        except:
            return None
    
    async def get_extension_details(self, extension_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific extension from Open VSX"""
        try:
            namespace, name = extension_id.split(".", 1)
            
            # Fetch extension details from Open VSX API
            api_url = f"https://open-vsx.org/api/{namespace}/{name}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    headers=VSCODE_MARKETPLACE_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        ext_data = await response.json()
                        return self._parse_openvsx_extension(ext_data)
                    else:
                        logger.warning(f"Extension {extension_id} not found in Open VSX (status {response.status})")
                        # Fallback to search
                        result = await self.search_extensions(query=extension_id, page_size=1)
                        if result.get("extensions"):
                            return result["extensions"][0]
                        return None
        except Exception as e:
            logger.error(f"Error getting extension details: {e}", exc_info=True)
            return None
    
    async def get_popular_extensions(self, category: str = "all", limit: int = 20) -> List[Dict[str, Any]]:
        """Get popular extensions"""
        result = await self.search_extensions(category=category, page_size=limit)
        extensions = result.get("extensions", [])
        
        # Sort by downloads
        extensions.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        
        return extensions[:limit]

