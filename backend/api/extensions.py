from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
import os
import json
from pathlib import Path

router = APIRouter()

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
    search: Optional[str] = Query("", description="Search query")
):
    """Get list of available extensions"""
    try:
        # Filter by category
        filtered = MOCK_EXTENSIONS
        if category and category != "all":
            category_map = {
                "mcp_servers": "MCP Servers",
                "themes": "Themes",
                "icon_themes": "Icon Themes",
                "languages": "Languages",
                "grammars": "Grammars",
                "language_servers": "Language Servers",
                "agent_servers": "Agent Servers",
                "snippets": "Snippets"
            }
            category_name = category_map.get(category, category)
            filtered = [ext for ext in MOCK_EXTENSIONS if ext.get("category") == category_name]
        
        # Filter by search query
        if search:
            search_lower = search.lower()
            filtered = [
                ext for ext in filtered
                if search_lower in ext.get("name", "").lower() or
                   search_lower in ext.get("description", "").lower() or
                   search_lower in ext.get("author", "").lower()
            ]
        
        return {"extensions": filtered}
    except Exception as e:
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
        # Check if it's an available extension
        extension = next((ext for ext in MOCK_EXTENSIONS if ext["id"] == extension_id), None)
        if not extension:
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' not found")
        
        # Check if it's installed
        installed = load_installed_extensions()
        is_installed = any(ext["id"] == extension_id for ext in installed)
        
        # Generate usage instructions based on extension type
        usage_instructions = generate_usage_instructions(extension)
        
        return {
            "extension": extension,
            "installed": is_installed,
            "usage_instructions": usage_instructions
        }
    except HTTPException:
        raise
    except Exception as e:
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

@router.post("/{extension_id}/install")
async def install_extension(extension_id: str):
    """Install an extension"""
    try:
        # Find the extension
        extension = next((ext for ext in MOCK_EXTENSIONS if ext["id"] == extension_id), None)
        if not extension:
            raise HTTPException(status_code=404, detail=f"Extension '{extension_id}' not found")
        
        # Load currently installed extensions
        installed = load_installed_extensions()
        
        # Check if already installed
        if any(ext["id"] == extension_id for ext in installed):
            return {"message": "Extension already installed", "extension": extension}
        
        # Add to installed list
        installed.append({
            **extension,
            "installed_at": str(Path(__file__).stat().st_mtime)  # Simple timestamp
        })
        
        # Save to config file
        save_installed_extensions(installed)
        
        # In a real implementation, you would:
        # 1. Download the extension from the repository
        # 2. Install dependencies
        # 3. Configure the extension
        # 4. Register it with the MCP system
        
        return {"message": "Extension installed successfully", "extension": extension}
    except HTTPException:
        raise
    except Exception as e:
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

