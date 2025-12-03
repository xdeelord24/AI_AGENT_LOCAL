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
from pathlib import Path as PathLib

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
            extension_root = extract_dir  # Track the root directory for theme file resolution
            
            if not package_json_path.exists():
                # Try extension subdirectory (VSIX files often have extension folder inside)
                for subdir in extract_dir.iterdir():
                    if subdir.is_dir():
                        potential_package = subdir / "package.json"
                        if potential_package.exists():
                            package_json_path = potential_package
                            extension_root = subdir  # Update extension_root to subdirectory
                            logger.info(f"Found package.json in subdirectory: {subdir.name}")
                            break
            
            # If still not found, search recursively
            if not package_json_path.exists():
                logger.info(f"Searching recursively for package.json in {extract_dir}")
                for root, dirs, files in os.walk(extract_dir):
                    if "package.json" in files:
                        package_json_path = Path(root) / "package.json"
                        extension_root = Path(root)  # Update extension_root to found directory
                        logger.info(f"Found package.json at: {package_json_path}")
                        break
            
            if not package_json_path.exists():
                logger.warning(f"No package.json found for {extension_id} in {extract_dir}")
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
            
            logger.info(f"Found {len(themes)} theme(s) in {extension_id}")
            
            # Extract each theme
            extracted_themes = []
            for theme_def in themes:
                theme_path = theme_def.get("path", "")
                theme_label = theme_def.get("label", extension_data.get("name", extension_id))
                theme_id = theme_def.get("id", extension_id)
                ui_theme = theme_def.get("uiTheme", "vs-dark")  # vs-dark, vs-light, hc-dark, hc-light
                
                if theme_path:
                    # Resolve theme file path relative to extension_root (where package.json is)
                    full_theme_path = extension_root / theme_path.lstrip("/")
                    if not full_theme_path.exists():
                        # Try relative to package.json directory
                        full_theme_path = package_json_path.parent / theme_path.lstrip("/")
                    
                    if not full_theme_path.exists():
                        # Try absolute path from extract_dir
                        full_theme_path = extract_dir / theme_path.lstrip("/")
                    
                    if full_theme_path.exists():
                        # Copy theme file to themes directory
                        theme_storage_path = self.themes_dir / f"{extension_id}_{theme_id}.json"
                        shutil.copy2(full_theme_path, theme_storage_path)
                        logger.info(f"Copied theme file from {full_theme_path} to {theme_storage_path}")
                        
                        # Read and parse theme
                        with open(full_theme_path, 'r', encoding='utf-8') as f:
                            theme_data = json.load(f)
                        
                        extracted_themes.append({
                            "id": f"{extension_id}_{theme_id}",  # Full ID for lookup
                            "theme_id": theme_id,  # Original theme ID
                            "label": theme_label,
                            "path": str(theme_storage_path),
                            "ui_theme": ui_theme,
                            "colors": theme_data.get("colors", {}),
                            "tokenColors": theme_data.get("tokenColors", []),
                            "extension_id": extension_id,
                            "extension_name": extension_data.get("name", extension_id)
                        })
                        
                        logger.info(f"Extracted theme '{theme_label}' (ID: {theme_id}) from {extension_id}")
                    else:
                        logger.warning(f"Theme file not found: {theme_path} (tried: {full_theme_path})")
            
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
                
                # Extract theme ID and extension ID from filename
                # Format: {extension_id}_{theme_id}.json
                filename = theme_file.stem
                parts = filename.rsplit("_", 1)
                
                if len(parts) == 2:
                    extension_id, theme_id = parts
                else:
                    # Fallback: use filename as both
                    extension_id = filename
                    theme_id = filename
                
                # Try to get label from theme data or use theme_id
                label = theme_data.get("name", theme_id)
                
                themes.append({
                    "id": filename,  # Use full filename as ID for lookup
                    "theme_id": theme_id,  # Original theme ID
                    "label": label,
                    "path": str(theme_file),
                    "colors": theme_data.get("colors", {}),
                    "tokenColors": theme_data.get("tokenColors", []),
                    "extension_id": extension_id,
                    "extension_name": extension_id.replace(".", " ").title()  # Fallback name
                })
            except Exception as e:
                logger.warning(f"Error reading theme file {theme_file}: {e}")
        
        # Also check installed extensions for theme metadata
        try:
            from .vscode_extension_service import VSCodeExtensionService
            installed_extensions_dir = self.extensions_dir
            
            for ext_dir in installed_extensions_dir.iterdir():
                if not ext_dir.is_dir():
                    continue
                
                # Check if this extension has themes
                extracted_dir = ext_dir / "extracted"
                if not extracted_dir.exists():
                    continue
                
                package_json = extracted_dir / "package.json"
                if not package_json.exists():
                    # Try subdirectories
                    for subdir in extracted_dir.iterdir():
                        if subdir.is_dir():
                            potential_package = subdir / "package.json"
                            if potential_package.exists():
                                package_json = potential_package
                                break
                
                if package_json.exists():
                    try:
                        with open(package_json, 'r', encoding='utf-8') as f:
                            package_data = json.load(f)
                        
                        contributes = package_data.get("contributes", {})
                        theme_defs = contributes.get("themes", [])
                        
                        for theme_def in theme_defs:
                            theme_id = theme_def.get("id", "")
                            theme_label = theme_def.get("label", package_data.get("displayName", ext_dir.name))
                            theme_path = theme_def.get("path", "")
                            
                            # Check if theme file exists in themes directory
                            theme_filename = f"{ext_dir.name}_{theme_id}.json"
                            theme_file = self.themes_dir / theme_filename
                            
                            if theme_file.exists():
                                # Already added from themes directory scan
                                continue
                            
                            # Try to find and add theme
                            if theme_path:
                                full_theme_path = extracted_dir / theme_path.lstrip("/")
                                if not full_theme_path.exists():
                                    full_theme_path = extracted_dir / theme_path
                                
                                if full_theme_path.exists():
                                    # Copy to themes directory if not already there
                                    if not theme_file.exists():
                                        shutil.copy2(full_theme_path, theme_file)
                                    
                                    # Read theme data
                                    with open(full_theme_path, 'r', encoding='utf-8') as f:
                                        theme_data = json.load(f)
                                    
                                    themes.append({
                                        "id": theme_filename,
                                        "theme_id": theme_id,
                                        "label": theme_label,
                                        "path": str(theme_file),
                                        "colors": theme_data.get("colors", {}),
                                        "tokenColors": theme_data.get("tokenColors", []),
                                        "extension_id": ext_dir.name,
                                        "extension_name": package_data.get("displayName", ext_dir.name)
                                    })
                    except Exception as e:
                        logger.warning(f"Error processing extension {ext_dir.name}: {e}")
        except Exception as e:
            logger.warning(f"Error scanning extensions for themes: {e}")
        
        return themes
    
    def get_theme_data(self, theme_id: str) -> Optional[Dict[str, Any]]:
        """Get theme data by theme ID (can be full ID like 'publisher.name_themeid' or just theme_id)"""
        # Try exact match first
        theme_file = self.themes_dir / f"{theme_id}.json"
        if not theme_file.exists():
            # Try to find by partial match (if theme_id is just the theme part)
            matching_files = list(self.themes_dir.glob(f"*_{theme_id}.json"))
            if matching_files:
                theme_file = matching_files[0]
                logger.info(f"Found theme file by partial match: {theme_file.name}")
        
        if theme_file.exists():
            try:
                with open(theme_file, 'r', encoding='utf-8') as f:
                    theme_data = json.load(f)
                    
                # VSCode themes can have colors at root level or nested
                # Ensure colors are at root level for easier access
                if "colors" not in theme_data:
                    # Check if colors are nested (some themes structure differently)
                    if "$schema" in theme_data and "colors" in theme_data.get("$schema", ""):
                        # This is unusual but handle it
                        pass
                    
                    # Some themes might have empty colors dict - that's valid but warn
                    if not theme_data.get("colors"):
                        logger.warning(f"Theme {theme_id} has no 'colors' property. Available keys: {list(theme_data.keys())}")
                        # Create empty colors dict to prevent errors
                        theme_data["colors"] = {}
                
                # Add metadata
                theme_data["id"] = theme_file.stem
                theme_data["path"] = str(theme_file)
                
                logger.info(f"Successfully loaded theme {theme_id} with {len(theme_data.get('colors', {}))} color definitions")
                return theme_data
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in theme file {theme_file}: {e}")
            except Exception as e:
                logger.error(f"Error reading theme {theme_id}: {e}", exc_info=True)
        else:
            logger.warning(f"Theme file not found: {theme_file}. Theme ID: {theme_id}")
            # List available theme files for debugging
            if self.themes_dir.exists():
                available_files = list(self.themes_dir.glob("*.json"))
                logger.info(f"Available theme files: {[f.name for f in available_files]}")
        return None

