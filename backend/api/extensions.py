from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
import os
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Import VSCode extension service
try:
    import sys
    from pathlib import Path
    # Add backend directory to path for imports
    backend_path = Path(__file__).parent.parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    
    from services.vscode_extension_service import VSCodeExtensionService
    VSCODE_SERVICE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"VSCode extension service not available: {e}")
    VSCODE_SERVICE_AVAILABLE = False
    VSCodeExtensionService = None

router = APIRouter()

# Initialize VSCode extension service if available
vscode_service = None
if VSCODE_SERVICE_AVAILABLE and VSCodeExtensionService:
    try:
        vscode_service = VSCodeExtensionService()
        logger.info("VSCode extension service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize VSCode extension service: {e}", exc_info=True)
        vscode_service = None
else:
    logger.warning(f"VSCode service not available. VSCODE_SERVICE_AVAILABLE={VSCODE_SERVICE_AVAILABLE}, VSCodeExtensionService={VSCodeExtensionService}")

# Path to MCP configuration file
MCP_CONFIG_DIR = Path(os.getenv("AI_AGENT_CONFIG_DIR", os.path.expanduser("~/.ai_agent")))
MCP_CONFIG_FILE = MCP_CONFIG_DIR / "mcp_config.json"

# Mock data for MCP server extensions (in a real implementation, this would come from a registry/API)
MOCK_EXTENSIONS = [
    {
        "id": "context7-mcp-server",
        "name": "Context7 MCP Server",
        "version": "v0.0.5",
        "category": "MCP Servers",
        "description": "Model Context Protocol Server for Context7",
        "author": "Akbxr <hi@akbxr.com>",
        "downloads": 73878,
        "repository": "https://github.com/akbxr/context7-mcp-server"
    },
    {
        "id": "github-mcp-server",
        "name": "GitHub MCP Server",
        "version": "v0.1.0",
        "category": "MCP Servers",
        "description": "Model Context Protocol Server for GitHub",
        "author": "Jeffrey Guenther <guenther.jeffrey@gmail.com>",
        "downloads": 48276,
        "repository": "https://github.com/jeffreyguenther/github-mcp-server"
    },
    {
        "id": "postgres-context-server",
        "name": "Postgres Context Server",
        "version": "v0.0.5",
        "category": "MCP Servers",
        "description": "Model Context Server for PostgreSQL",
        "author": "Max Brunsfeld <max@zed.dev>",
        "downloads": 47872,
        "repository": "https://github.com/maxbrunsfeld/postgres-context-server"
    },
    {
        "id": "sequential-thinking-mcp-server",
        "name": "Sequential Thinking MCP Server",
        "version": "v0.1.0",
        "category": "MCP Servers",
        "description": "Model Context Protocol Server for Sequential Thinking",
        "author": "Jeffrey Guenther <guenther.jeffrey@gmail.com>",
        "downloads": 39661,
        "repository": "https://github.com/jeffreyguenther/sequential-thinking-mcp-server"
    },
    {
        "id": "brave-search-mcp-server",
        "name": "Brave Search MCP Server",
        "version": "v0.2.0",
        "category": "MCP Servers",
        "description": "Model Context Protocol Server for Brave Search",
        "author": "Zed Industries <support@zed.dev>",
        "downloads": 30021,
        "repository": "https://github.com/zed-industries/brave-search-mcp-server"
    },
    {
        "id": "document-slide-creator-mcp-server",
        "name": "Document & Slide Creator MCP Server",
        "version": "v1.0.0",
        "category": "MCP Servers",
        "description": "Create Microsoft Word documents (.docx) and PowerPoint presentations (.pptx) - similar to Google Docs and Google Slides",
        "author": "AI Agent Local",
        "downloads": 0,
        "repository": "https://github.com/ai-agent-local/document-slide-creator"
    }
]

# Path to store installed extensions info
EXTENSIONS_CONFIG_DIR = Path(os.getenv("AI_AGENT_CONFIG_DIR", os.path.expanduser("~/.ai_agent")))
EXTENSIONS_CONFIG_FILE = EXTENSIONS_CONFIG_DIR / "installed_extensions.json"

def ensure_extensions_config_dir():
    """Ensure the extensions config directory exists"""
    EXTENSIONS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_installed_extensions() -> List[Dict[str, Any]]:
    """Load list of installed extensions from config file"""
    ensure_extensions_config_dir()
    if not EXTENSIONS_CONFIG_FILE.exists():
        return []
    try:
        with open(EXTENSIONS_CONFIG_FILE, 'r') as f:
            data = json.load(f)
            return data.get("extensions", [])
    except Exception as e:
        print(f"Error loading installed extensions: {e}")
        return []

def save_installed_extensions(extensions: List[Dict[str, Any]]):
    """Save list of installed extensions to config file"""
    ensure_extensions_config_dir()
    try:
        with open(EXTENSIONS_CONFIG_FILE, 'w') as f:
            json.dump({"extensions": extensions}, f, indent=2)
    except Exception as e:
        print(f"Error saving installed extensions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save installed extensions: {str(e)}")

@router.get("")
async def get_extensions(
    category: Optional[str] = Query("all", description="Filter by category"),
    search: Optional[str] = Query("", description="Search query"),
    source: Optional[str] = Query("all", description="Extension source: 'all', 'mcp', or 'vscode'")
):
    """Get list of available extensions from MCP and VSCode marketplace"""
    try:
        all_extensions = []
        
        # Get MCP extensions
        if source in ("all", "mcp"):
            mcp_extensions = MOCK_EXTENSIONS.copy()
            
            # Filter MCP extensions by category
            if category and category != "all":
                category_map = {
                    "mcp_servers": "MCP Servers",
                }
                category_name = category_map.get(category)
                if category_name:
                    mcp_extensions = [ext for ext in mcp_extensions if ext.get("category") == category_name]
                elif category not in ["themes", "icon_themes", "languages", "grammars", "language_servers", "snippets", "debuggers", "formatters", "linters"]:
                    # If category doesn't match VSCode categories, filter MCP extensions
                    mcp_extensions = []
            
            # Filter MCP extensions by search
            if search:
                search_lower = search.lower()
                mcp_extensions = [
                    ext for ext in mcp_extensions
                    if search_lower in ext.get("name", "").lower() or
                       search_lower in ext.get("description", "").lower() or
                       search_lower in ext.get("author", "").lower()
                ]
            
            # Add extension type marker
            for ext in mcp_extensions:
                ext["extension_type"] = "mcp"
            
            all_extensions.extend(mcp_extensions)
        
        # Get VSCode extensions
        if source in ("all", "vscode"):
            if not vscode_service:
                logger.warning("VSCode service not available when trying to fetch extensions")
            else:
                try:
                    logger.info(f"Fetching VSCode extensions: category={category}, search={search}, source={source}")
                    vscode_result = await vscode_service.search_extensions(
                        query=search or "",
                        category=category if category != "mcp_servers" else "all",
                        page_size=50
                    )
                    
                    vscode_extensions = vscode_result.get("extensions", [])
                    logger.info(f"Fetched {len(vscode_extensions)} VSCode extensions")
                    
                    # Filter by category if needed
                    if category and category != "all" and category != "mcp_servers":
                        category_map = {
                            "themes": "Themes",
                            "icon_themes": "Icon Themes",
                            "languages": "Languages",
                            "grammars": "Grammars",
                            "language_servers": "Language Servers",
                            "snippets": "Snippets",
                            "debuggers": "Debuggers",
                            "formatters": "Formatters",
                            "linters": "Linters"
                        }
                        category_name = category_map.get(category)
                        if category_name:
                            vscode_extensions = [
                                ext for ext in vscode_extensions
                                if ext.get("category") == category_name
                            ]
                            logger.info(f"Filtered to {len(vscode_extensions)} extensions in category {category_name}")
                    
                    all_extensions.extend(vscode_extensions)
                except Exception as e:
                    logger.error(f"Error fetching VSCode extensions: {e}", exc_info=True)
                    # Continue without VSCode extensions if there's an error
        
        # Sort by downloads (if available) or name
        all_extensions.sort(key=lambda x: (
            -x.get("downloads", 0),
            x.get("name", "").lower()
        ))
        
        result = {
            "extensions": all_extensions,
            "total": len(all_extensions),
            "sources": {
                "mcp": source in ("all", "mcp"),
                "vscode": source in ("all", "vscode") and vscode_service is not None
            },
            "debug": {
                "vscode_service_available": vscode_service is not None,
                "vscode_service_initialized": VSCODE_SERVICE_AVAILABLE
            }
        }
        logger.info(f"Returning {len(all_extensions)} extensions (MCP: {len([e for e in all_extensions if e.get('extension_type') == 'mcp'])}, VSCode: {len([e for e in all_extensions if e.get('extension_type') == 'vscode'])})")
        return result
    except Exception as e:
        logger.error(f"Error fetching extensions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch extensions: {str(e)}")

@router.get("/installed")
async def get_installed_extensions():
    """Get list of installed extensions"""
    try:
        installed = load_installed_extensions()
        return {"extensions": installed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch installed extensions: {str(e)}")

@router.get("/{extension_id}")
async def get_extension_details(extension_id: str):
    """Get details and usage instructions for a specific extension"""
    try:
        extension = None
        
        # Check MCP extensions first
        extension = next((ext for ext in MOCK_EXTENSIONS if ext["id"] == extension_id), None)
        
        # If not found in MCP, check VSCode marketplace
        if not extension and vscode_service:
            try:
                extension = await vscode_service.get_extension_details(extension_id)
            except Exception as e:
                logger.error(f"Error fetching VSCode extension details: {e}")
        
        if not extension:
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' not found")
        
        # Check if it's installed
        installed = load_installed_extensions()
        is_installed = any(ext["id"] == extension_id for ext in installed)
        
        # Generate usage instructions based on extension type
        extension_type = extension.get("extension_type", "mcp")
        if extension_type == "mcp":
            usage_instructions = generate_usage_instructions(extension)
        else:
            usage_instructions = generate_vscode_usage_instructions(extension)
        
        return {
            "extension": extension,
            "installed": is_installed,
            "usage_instructions": usage_instructions
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching extension details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch extension details: {str(e)}")

def generate_usage_instructions(extension: Dict[str, Any]) -> Dict[str, Any]:
    """Generate usage instructions for an extension"""
    extension_id = extension.get("id", "")
    category = extension.get("category", "")
    repository = extension.get("repository", "")
    
    instructions = {
        "title": f"How to use {extension.get('name', 'Extension')}",
        "steps": [],
        "notes": []
    }
    
    if category == "MCP Servers":
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the MCP Server",
                "description": f"Install the MCP server package. Check the repository for installation instructions: {repository}"
            },
            {
                "step": 2,
                "title": "Configure MCP Server",
                "description": f"Add the MCP server to your MCP configuration file. The configuration file is typically located at `~/.ai_agent/mcp_config.json` or set via the `AI_AGENT_CONFIG_DIR` environment variable."
            },
            {
                "step": 3,
                "title": "Restart the Application",
                "description": "Restart the backend server to load the new MCP server configuration."
            },
            {
                "step": 4,
                "title": "Use in Chat",
                "description": "The MCP server tools will be automatically available in your AI chat. The AI can use the tools provided by this extension when appropriate."
            }
        ]
        
        # Add example configuration based on extension type
        if "github" in extension_id.lower():
            instructions["example_config"] = {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token_here"
                }
            }
        elif "postgres" in extension_id.lower():
            instructions["example_config"] = {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "mcp_server_postgres"],
                "env": {
                    "POSTGRES_CONNECTION_STRING": "postgresql://user:password@localhost:5432/dbname"
                }
            }
        elif "brave" in extension_id.lower():
            instructions["example_config"] = {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@brave/mcp-server-brave-search"],
                "env": {
                    "BRAVE_API_KEY": "your_api_key_here"
                }
            }
        elif "document" in extension_id.lower() or "slide" in extension_id.lower():
            instructions["example_config"] = {
                "type": "builtin",
                "description": "This MCP server is built into the AI Agent. No additional configuration needed.",
                "tools": [
                    "create_document - Create Word documents (.docx)",
                    "create_slide - Create PowerPoint slides (.pptx)",
                    "create_presentation - Create full presentations (.pptx)"
                ],
                "requirements": [
                    "pip install python-docx python-pptx"
                ]
            }
        
        instructions["notes"] = [
            "MCP servers run as separate processes and communicate via stdio or HTTP",
            "Make sure you have the required dependencies installed (Node.js, Python, etc.)",
            "API keys and credentials should be stored securely in environment variables",
            "Check the extension's repository for specific setup requirements"
        ]
    
    return instructions

def generate_vscode_usage_instructions(extension: Dict[str, Any]) -> Dict[str, Any]:
    """Generate usage instructions for VSCode extensions"""
    extension_id = extension.get("id", "")
    category = extension.get("category", "")
    marketplace_url = extension.get("marketplace_url", "")
    repository_url = extension.get("repository_url", "")
    is_compatible = extension.get("is_compatible", True)
    
    instructions = {
        "title": f"How to use {extension.get('name', 'Extension')}",
        "steps": [],
        "notes": []
    }
    
    if category == "Themes" or category == "Icon Themes":
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the Extension",
                "description": f"Click the 'Install' button to add this extension to your system. The extension will be downloaded and installed automatically."
            },
            {
                "step": 2,
                "title": "Activate the Theme",
                "description": "After installation, go to Settings > Appearance and select this theme from the theme selector."
            },
            {
                "step": 3,
                "title": "Restart if Needed",
                "description": "Some themes may require a restart of the application to take full effect."
            }
        ]
    elif category == "Languages" or category == "Grammars":
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the Extension",
                "description": f"Click the 'Install' button to add language support. Syntax highlighting and language features will be enabled automatically."
            },
            {
                "step": 2,
                "title": "Open Files",
                "description": "Open files with the supported file extensions to see syntax highlighting and language features."
            }
        ]
    elif category == "Language Servers":
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the Extension",
                "description": f"Click the 'Install' button to add the language server. This provides advanced features like autocomplete, error checking, and refactoring."
            },
            {
                "step": 2,
                "title": "Install Language Server",
                "description": "The extension may require additional setup. Check the extension's documentation for specific requirements."
            },
            {
                "step": 3,
                "title": "Configure if Needed",
                "description": "Some language servers require configuration. Check Settings > Extensions for configuration options."
            }
        ]
    elif category == "Snippets":
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the Extension",
                "description": f"Click the 'Install' button to add code snippets. Snippets will be available immediately after installation."
            },
            {
                "step": 2,
                "title": "Use Snippets",
                "description": "Type the snippet prefix and press Tab to expand the snippet. Check the extension documentation for available snippets."
            }
        ]
    else:
        instructions["steps"] = [
            {
                "step": 1,
                "title": "Install the Extension",
                "description": f"Click the 'Install' button to add this extension. Features will be available after installation."
            },
            {
                "step": 2,
                "title": "Check Documentation",
                "description": f"Visit the extension's marketplace page for detailed usage instructions: {marketplace_url}"
            }
        ]
    
    if not is_compatible:
        instructions["notes"].append(
            "⚠️ This extension may have limited compatibility with this system. Some features might not work as expected."
        )
    
    instructions["notes"].extend([
        f"Marketplace URL: {marketplace_url}",
        "Extensions are installed locally and do not require internet access after installation.",
        "Some extensions may require additional dependencies or configuration."
    ])
    
    if repository_url:
        instructions["notes"].append(f"Repository: {repository_url}")
    
    return instructions

@router.post("/{extension_id}/install")
async def install_extension(extension_id: str):
    """Install an extension (MCP or VSCode)"""
    try:
        extension = None
        extension_type = "mcp"
        
        # Find the extension - check MCP first
        extension = next((ext for ext in MOCK_EXTENSIONS if ext["id"] == extension_id), None)
        
        # If not found in MCP, check VSCode marketplace
        if not extension and vscode_service:
            try:
                extension = await vscode_service.get_extension_details(extension_id)
                if extension:
                    extension_type = "vscode"
            except Exception as e:
                logger.error(f"Error fetching VSCode extension for installation: {e}")
        
        if not extension:
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' not found")
        
        # Load currently installed extensions
        installed = load_installed_extensions()
        
        # Check if already installed
        if any(ext["id"] == extension_id for ext in installed):
            return {"message": "Extension already installed", "extension": extension}
        
        # Prepare extension data for installation
        extension_data = {
            **extension,
            "extension_type": extension_type,
            "installed_at": str(Path(__file__).stat().st_mtime)
        }
        
        # For VSCode extensions, add installation metadata
        if extension_type == "vscode":
            extension_data["vsix_url"] = extension.get("vsix_url")
            extension_data["marketplace_url"] = extension.get("marketplace_url")
            extension_data["is_compatible"] = extension.get("is_compatible", True)
        
        # Add to installed list
        installed.append(extension_data)
        
        # Save to config file
        save_installed_extensions(installed)
        
        # For VSCode extensions, we would download and extract the VSIX file here
        # For MCP extensions, we would configure them in the MCP config
        # This is a simplified implementation - in production, you'd want to:
        # 1. Download VSIX file for VSCode extensions
        # 2. Extract and install to extensions directory
        # 3. For MCP extensions, add to MCP config file
        # 4. Register with the system
        
        return {
            "message": "Extension installed successfully",
            "extension": extension_data,
            "type": extension_type,
            "note": "Extension has been registered. Some extensions may require a restart to take effect."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing extension: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install extension: {str(e)}")

@router.delete("/{extension_id}/install")
async def uninstall_extension(extension_id: str):
    """Uninstall an extension"""
    try:
        # Load currently installed extensions
        installed = load_installed_extensions()
        
        # Check if installed
        if not any(ext["id"] == extension_id for ext in installed):
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' is not installed")
        
        # Remove from installed list
        installed = [ext for ext in installed if ext["id"] != extension_id]
        
        # Save to config file
        save_installed_extensions(installed)
        
        # In a real implementation, you would:
        # 1. Unregister the extension from the MCP system
        # 2. Remove configuration
        # 3. Clean up files
        
        return {"message": "Extension uninstalled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to uninstall extension: {str(e)}")

@router.get("/mcp/config")
async def get_mcp_config():
    """Get MCP server configuration"""
    try:
        # Ensure config directory exists
        MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Check if config file exists
        if not MCP_CONFIG_FILE.exists():
            return {
                "config_file_path": str(MCP_CONFIG_FILE),
                "exists": False,
                "config": None,
                "message": "MCP configuration file does not exist. Create it to configure MCP servers."
            }
        
        # Read config file
        try:
            with open(MCP_CONFIG_FILE, 'r') as f:
                config = json.load(f)
            
            return {
                "config_file_path": str(MCP_CONFIG_FILE),
                "exists": True,
                "config": config,
                "message": "MCP configuration loaded successfully"
            }
        except json.JSONDecodeError as e:
            return {
                "config_file_path": str(MCP_CONFIG_FILE),
                "exists": True,
                "config": None,
                "error": f"Invalid JSON in config file: {str(e)}",
                "message": "MCP configuration file exists but contains invalid JSON"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read MCP configuration: {str(e)}")

@router.get("/{extension_id}/config")
async def get_extension_config(extension_id: str):
    """Get configuration for a specific installed MCP server extension"""
    try:
        # Check if extension is installed
        installed = load_installed_extensions()
        extension = next((ext for ext in installed if ext["id"] == extension_id), None)
        
        if not extension:
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' is not installed")
        
        # Check if it's an MCP server
        if extension.get("category") != "MCP Servers":
            return {
                "extension_id": extension_id,
                "has_config": False,
                "message": "This extension is not an MCP server and does not require configuration"
            }
        
        # Read MCP config
        MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        if not MCP_CONFIG_FILE.exists():
            return {
                "extension_id": extension_id,
                "extension_name": extension.get("name"),
                "has_config": False,
                "config_file_path": str(MCP_CONFIG_FILE),
                "config": None,
                "message": "MCP configuration file does not exist. You need to add this server to the MCP config file.",
                "example_config": generate_usage_instructions(extension).get("example_config")
            }
        
        # Read and find this extension's config
        try:
            with open(MCP_CONFIG_FILE, 'r') as f:
                mcp_config = json.load(f)
            
            # Look for this extension in the config
            # MCP config format: {"mcpServers": {"server_name": {...}}}
            servers = mcp_config.get("mcpServers", {})
            extension_config = None
            
            # Try to find by extension ID or name
            for server_name, server_config in servers.items():
                if extension_id in server_name.lower() or extension.get("name", "").lower() in server_name.lower():
                    extension_config = {
                        "server_name": server_name,
                        "config": server_config
                    }
                    break
            
            if extension_config:
                return {
                    "extension_id": extension_id,
                    "extension_name": extension.get("name"),
                    "has_config": True,
                    "config_file_path": str(MCP_CONFIG_FILE),
                    "config": extension_config,
                    "message": "Configuration found for this MCP server"
                }
            else:
                return {
                    "extension_id": extension_id,
                    "extension_name": extension.get("name"),
                    "has_config": False,
                    "config_file_path": str(MCP_CONFIG_FILE),
                    "config": None,
                    "message": "Extension is installed but not configured in MCP config file",
                    "example_config": generate_usage_instructions(extension).get("example_config")
                }
        except json.JSONDecodeError as e:
            return {
                "extension_id": extension_id,
                "extension_name": extension.get("name"),
                "has_config": False,
                "config_file_path": str(MCP_CONFIG_FILE),
                "error": f"Invalid JSON in config file: {str(e)}",
                "message": "MCP configuration file contains invalid JSON"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get extension configuration: {str(e)}")

