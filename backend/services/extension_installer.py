"""
Extension Installer Service

Handles downloading, extracting, and installing VSCode extensions.
Specifically handles theme extraction and application.
"""

import os
import json
import zipfile
import aiohttp
import aiofiles
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import shutil

logger = logging.getLogger(__name__)

# Extension installation directory
EXTENSIONS_DIR = Path(os.getenv("AI_AGENT_CONFIG_DIR", os.path.expanduser("~/.ai_agent"))) / "extensions"
EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Theme storage directory
THEMES_DIR = EXTENSIONS_DIR / "themes"
THEMES_DIR.mkdir(parents=True, exist_ok=True)


class ExtensionInstaller:
    """Service for installing VSCode extensions"""
    
    def __init__(self):
        self.extensions_dir = EXTENSIONS_DIR
        self.themes_dir = THEMES_DIR
    
    async def install_extension(self, extension_id: str, vsix_url: str, extension_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Install a VSCode extension by downloading and extracting VSIX file
        
        Args:
            extension_id: Extension identifier (e.g., "publisher.name")
            vsix_url: URL to download VSIX file
            extension_data: Extension metadata
            
        Returns:
            Installation result with paths and extracted files
        """
        try:
            # Create extension directory
            ext_dir = self.extensions_dir / extension_id
            ext_dir.mkdir(parents=True, exist_ok=True)
            
            # Download VSIX file
            vsix_path = ext_dir / f"{extension_id}.vsix"
            logger.info(f"Downloading extension from {vsix_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(vsix_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to download VSIX: HTTP {response.status}")
                    
                    async with aiofiles.open(vsix_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
            
            logger.info(f"Downloaded VSIX to {vsix_path}")
            
            # Extract VSIX (it's a ZIP file)
            extract_dir = ext_dir / "extracted"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir()
            
            with zipfile.ZipFile(vsix_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            logger.info(f"Extracted extension to {extract_dir}")
            
            # Process extension based on type
            category = extension_data.get("category", "")
            result = {
                "extension_id": extension_id,
                "installed_path": str(extract_dir),
                "vsix_path": str(vsix_path),
                "files": []
            }
            
            # If it's a theme, extract theme files
            if category in ("Themes", "Icon Themes"):
                theme_result = await self._extract_theme(extension_id, extract_dir, extension_data)
                result.update(theme_result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error installing extension {extension_id}: {e}", exc_info=True)
            raise
    
    async def _extract_theme(self, extension_id: str, extract_dir: Path, extension_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract theme files from extension"""
        try:
            # Look for package.json to find theme contributions
            package_json_path = extract_dir / "package.json"
            if not package_json_path.exists():
                # Try extension subdirectory
                for subdir in extract_dir.iterdir():
                    if subdir.is_dir():
                        potential_package = subdir / "package.json"
                        if potential_package.exists():
                            package_json_path = potential_package
                            break
            
            if not package_json_path.exists():
                logger.warning(f"No package.json found for {extension_id}")
                return {"themes": []}
            
            # Read package.json
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            # Find theme contributions
            contributes = package_data.get("contributes", {})
            themes = contributes.get("themes", [])
            
            if not themes:
                logger.info(f"No themes found in {extension_id}")
                return {"themes": []}
            
            # Extract each theme
            extracted_themes = []
            for theme_def in themes:
                theme_path = theme_def.get("path", "")
                theme_label = theme_def.get("label", extension_data.get("name", extension_id))
                theme_id = theme_def.get("id", extension_id)
                ui_theme = theme_def.get("uiTheme", "vs-dark")  # vs-dark, vs-light, hc-dark, hc-light
                
                if theme_path:
                    # Resolve theme file path
                    full_theme_path = extract_dir / theme_path
                    if not full_theme_path.exists():
                        # Try relative to extension root
                        full_theme_path = extract_dir / theme_path.lstrip("/")
                    
                    if full_theme_path.exists():
                        # Copy theme file to themes directory
                        theme_storage_path = self.themes_dir / f"{extension_id}_{theme_id}.json"
                        shutil.copy2(full_theme_path, theme_storage_path)
                        
                        # Read and parse theme
                        with open(full_theme_path, 'r', encoding='utf-8') as f:
                            theme_data = json.load(f)
                        
                        extracted_themes.append({
                            "id": theme_id,
                            "label": theme_label,
                            "path": str(theme_storage_path),
                            "ui_theme": ui_theme,
                            "colors": theme_data.get("colors", {}),
                            "tokenColors": theme_data.get("tokenColors", []),
                            "extension_id": extension_id,
                            "extension_name": extension_data.get("name", extension_id)
                        })
                        
                        logger.info(f"Extracted theme '{theme_label}' from {extension_id}")
            
            return {
                "themes": extracted_themes,
                "theme_count": len(extracted_themes)
            }
            
        except Exception as e:
            logger.error(f"Error extracting theme from {extension_id}: {e}", exc_info=True)
            return {"themes": [], "error": str(e)}
    
    def get_installed_themes(self) -> List[Dict[str, Any]]:
        """Get list of all installed themes"""
        themes = []
        
        # Scan themes directory
        for theme_file in self.themes_dir.glob("*.json"):
            try:
                with open(theme_file, 'r', encoding='utf-8') as f:
                    theme_data = json.load(f)
                
                # Extract theme ID from filename
                theme_id = theme_file.stem
                extension_id = "_".join(theme_id.split("_")[:-1]) if "_" in theme_id else theme_id
                
                themes.append({
                    "id": theme_id,
                    "path": str(theme_file),
                    "colors": theme_data.get("colors", {}),
                    "tokenColors": theme_data.get("tokenColors", []),
                    "extension_id": extension_id
                })
            except Exception as e:
                logger.warning(f"Error reading theme file {theme_file}: {e}")
        
        return themes
    
    def get_theme_data(self, theme_id: str) -> Optional[Dict[str, Any]]:
        """Get theme data by theme ID"""
        theme_file = self.themes_dir / f"{theme_id}.json"
        if theme_file.exists():
            try:
                with open(theme_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading theme {theme_id}: {e}")
        return None

