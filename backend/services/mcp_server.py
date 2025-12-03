"""
Model Context Protocol (MCP) Server Implementation for AI Agent

The MCP Server acts as a standardized bridge between AI models and external systems,
providing unified connectivity, real-time access, and scalable integration.

Key Features:
- Unified Connectivity: Single standardized interface for all external tools and data sources
- Real-Time Access: Enables AI models to pull fresh, live information instead of static training data
- Scalability: Minimal setup required, reducing deployment time and complexity
- Flexibility: Extensible architecture that can integrate with any external service

Architecture:
The MCP Server implements the Model Context Protocol, allowing AI models to:
1. Discover available tools through standardized tool descriptions
2. Execute tools with structured parameters
3. Receive real-time results formatted for AI consumption
4. Access multiple data sources (files, web, code analysis) through one interface

This implementation provides tools for:
- File operations (read, write, list, search)
- Code analysis and search
- Web search with caching and optimization
- Command execution
- Directory tree navigation

The server follows the MCP protocol standard, ensuring compatibility with any
MCP-compliant AI model or client.
"""

import asyncio
import json
import os
import subprocess
import time
import logging
import aiofiles
import aiohttp
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Import here to avoid circular dependencies
MCP_AVAILABLE = False
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Create minimal stubs for when MCP is not available
    class Server:
        pass
    class stdio_server:
        pass
    
    # Simple Tool and TextContent classes for when MCP SDK is not available
    class Tool:
        def __init__(self, name: str, description: str, inputSchema: Dict[str, Any]):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema
    
    class TextContent:
        def __init__(self, type: str, text: str):
            self.type = type
            self.text = text


class MCPServerTools:
    """
    MCP Server Tools - Bridge between AI models and external systems
    
    This class implements the Model Context Protocol server, providing a unified
    interface for AI models to access external tools and data sources. It acts as
    the backend system that handles requests from AI models and routes them to
    the appropriate tools, APIs, or services.
    
    The MCP server provides:
    - Standardized tool discovery and execution
    - Real-time data access (files, web, code)
    - Caching for performance optimization
    - Error handling and validation
    
    This follows the MCP protocol standard, ensuring seamless integration with
    any MCP-compliant AI model or client.
    """
    
    def __init__(self, file_service=None, code_analyzer=None, web_search_enabled=True, web_search_service=None, workspace_root=None):
        self.file_service = file_service
        self.code_analyzer = code_analyzer
        self.web_search_enabled = web_search_enabled
        self.workspace_root = os.path.abspath(workspace_root) if workspace_root else os.getcwd()
        self._web_search_service = web_search_service  # Shared web search service instance
        try:
            self._cache_ttl_seconds = max(1, int(os.getenv("MCP_CACHE_TTL_SECONDS", "4")))
        except ValueError:
            self._cache_ttl_seconds = 4
        self._dir_cache: Dict[str, Dict[str, Any]] = {}
        self._tree_cache: Dict[str, Dict[str, Any]] = {}
        
        # Command execution loop prevention
        # Track recent commands to prevent infinite loops
        self._command_history: List[Dict[str, Any]] = []  # List of {command, timestamp} dicts
        self._max_command_history = 20  # Keep last 20 commands
        self._loop_detection_window = 30  # Seconds to look back for loops
        self._max_repeats = 3  # Maximum times same command can run in window
        
        # Tool metadata
        self.server_version = "1.0.0"
        self.server_capabilities = {
            "caching": True,
            "validation": True,
            "analytics": True,
            "error_recovery": True
        }

    def _build_cache_key(self, path: str, suffix: str = "") -> str:
        normalized = os.path.abspath(path)
        return f"{normalized}::{suffix}" if suffix else normalized

    def _get_cached_text(self, cache: Dict[str, Dict[str, Any]], key: str) -> Optional[str]:
        entry = cache.get(key)
        if not entry:
            return None
        if (time.time() - entry.get("ts", 0)) > self._cache_ttl_seconds:
            cache.pop(key, None)
            return None
        return entry.get("text")

    def _set_cached_text(self, cache: Dict[str, Dict[str, Any]], key: str, text: str) -> None:
        cache[key] = {"ts": time.time(), "text": text}

    def _invalidate_structure_caches(self) -> None:
        self._dir_cache.clear()
        self._tree_cache.clear()
    
    def _check_command_loop(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a command would create a loop by running the same command too many times.
        
        Returns:
            Tuple of (is_loop, error_message)
            - is_loop: True if this command would create a loop
            - error_message: Error message if loop detected, None otherwise
        """
        current_time = time.time()
        normalized_command = command.strip()
        
        # Clean old entries outside the detection window
        self._command_history = [
            entry for entry in self._command_history
            if (current_time - entry.get("timestamp", 0)) <= self._loop_detection_window
        ]
        
        # Count how many times this exact command was run recently
        recent_count = sum(
            1 for entry in self._command_history
            if entry.get("command", "").strip() == normalized_command
        )
        
        # Check if this would exceed the maximum repeats
        if recent_count >= self._max_repeats:
            return True, (
                f"LOOP PREVENTION: Command '{normalized_command}' has been executed "
                f"{recent_count} times in the last {self._loop_detection_window} seconds. "
                f"Maximum allowed repeats: {self._max_repeats}. "
                f"This prevents infinite loops. Please wait a moment or modify the command."
            )
        
        return False, None
    
    def _record_command_execution(self, command: str) -> None:
        """Record a command execution in the history for loop detection."""
        current_time = time.time()
        normalized_command = command.strip()
        
        # Add to history
        self._command_history.append({
            "command": normalized_command,
            "timestamp": current_time
        })
        
        # Keep only the most recent entries
        if len(self._command_history) > self._max_command_history:
            self._command_history = self._command_history[-self._max_command_history:]
    
    def set_workspace_root(self, workspace_path: str) -> None:
        """
        Update the workspace root path for MCP tool operations.
        This ensures tools operate within the correct workspace directory.
        """
        if workspace_path and workspace_path.strip():
            # Normalize the path - handle both absolute and relative paths
            normalized = workspace_path.strip().replace('\\', '/')
            # If it's a relative path, resolve it relative to current working directory
            if not os.path.isabs(normalized):
                resolved_path = os.path.abspath(os.path.join(os.getcwd(), normalized))
            else:
                resolved_path = os.path.abspath(normalized)
            
            # Verify the path exists and is a directory
            if os.path.exists(resolved_path) and os.path.isdir(resolved_path):
                old_root = self.workspace_root
                self.workspace_root = resolved_path
                # Invalidate caches when workspace changes
                if old_root != self.workspace_root:
                    self._invalidate_structure_caches()
                    logger.info(f"[MCP] Workspace root updated: {old_root} -> {self.workspace_root}")
            else:
                logger.warning(f"[MCP] Workspace path does not exist or is not a directory: {workspace_path} (resolved: {resolved_path}), keeping current: {self.workspace_root}")
        else:
            # Reset to default (current working directory) if no path provided
            old_root = self.workspace_root
            self.workspace_root = os.getcwd()
            if old_root != self.workspace_root:
                self._invalidate_structure_caches()
                logger.info(f"[MCP] Workspace root reset to default: {self.workspace_root}")
    
    def get_tools(self) -> List[Tool]:
        """
        Get list of available MCP tools
        
        This method implements the MCP protocol's tool discovery mechanism.
        It returns a standardized list of tools that AI models can use, with
        complete schema information for each tool.
        
        Returns:
            List of Tool objects following the MCP protocol specification
        """
        # Tool class is always available - either from mcp.types or from the fallback stub
        # defined at module level (lines 59-63). No need to check MCP_AVAILABLE or import.
        
        tools = [
            Tool(
                name="read_file",
                description="Read the contents of a file. Path can be relative to workspace root or absolute.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to read (relative to workspace or absolute)"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="write_file",
                description="Write content to a file. Creates the file if it doesn't exist. In ASK mode, this tool is disabled.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to write (relative to workspace or absolute)"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to the file"
                        }
                    },
                    "required": ["path", "content"]
                }
            ),
            Tool(
                name="list_directory",
                description="List files and directories in a given path",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to list (defaults to workspace root)",
                            "default": "."
                        }
                    }
                }
            ),
            Tool(
                name="search_files",
                description="Search for files by name pattern in the workspace",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "File name pattern to search for (supports wildcards)"
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (defaults to workspace root)",
                            "default": "."
                        }
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="get_file_tree",
                description="Get the directory tree structure of the workspace or a specific path",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to get tree for (defaults to workspace root)",
                            "default": "."
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum depth to traverse (default: 4)",
                            "default": 4
                        }
                    }
                }
            ),
            Tool(
                name="analyze_code",
                description="Analyze code in a file: extract functions, classes, imports, and dependencies",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the code file to analyze"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="grep_code",
                description="Search for text patterns in code files across the workspace",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Text pattern or regex to search for"
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (defaults to workspace root)",
                            "default": "."
                        },
                        "file_extensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "File extensions to limit search to (e.g., ['.py', '.js'])"
                        }
                    },
                    "required": ["pattern"]
                }
            ),
            Tool(
                name="execute_command",
                description="Execute a shell command in the workspace directory and return the output. Useful for investigating issues, testing code temporarily, checking file contents, running tests, or debugging. The command output (stdout and stderr) will be visible in the chat. Loop prevention is enabled to prevent infinite command execution.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute (e.g., 'ls -la', 'python test.py', 'npm test', 'git status')"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 30)",
                            "default": 30
                        }
                    },
                    "required": ["command"]
                }
            ),
            Tool(
                name="download_file",
                description="Download a file from a URL and save it to the workspace. Supports HTTP and HTTPS URLs.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL of the file to download (must be HTTP or HTTPS)"
                        },
                        "path": {
                            "type": "string",
                            "description": "Path where to save the file (relative to workspace or absolute). If not provided, filename will be extracted from URL."
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Download timeout in seconds (default: 60)",
                            "default": 60
                        }
                    },
                    "required": ["url"]
                }
            ),
            Tool(
                name="create_document",
                description="Create a Microsoft Word-like document (.docx) with formatted text, headings, paragraphs, lists, and tables. Similar to Google Docs or Microsoft Word.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path where to save the document (relative to workspace or absolute). Should end with .docx"
                        },
                        "title": {
                            "type": "string",
                            "description": "Document title"
                        },
                        "content": {
                            "type": "string",
                            "description": "Document content. Can include markdown-style formatting: # for headings, * for lists, ** for bold, etc."
                        },
                        "author": {
                            "type": "string",
                            "description": "Document author (optional)"
                        }
                    },
                    "required": ["path", "content"]
                }
            ),
            Tool(
                name="create_slide",
                description="Create a single PowerPoint slide (.pptx) with title, content, and optional images. Can be used to create individual slides or add to presentations.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path where to save the slide presentation (relative to workspace or absolute). Should end with .pptx"
                        },
                        "title": {
                            "type": "string",
                            "description": "Slide title"
                        },
                        "content": {
                            "type": "string",
                            "description": "Slide content (text, bullet points, etc.)"
                        },
                        "layout": {
                            "type": "string",
                            "description": "Slide layout: 'title_only', 'title_content', 'blank', 'title_slide' (default: 'title_content')",
                            "enum": ["title_only", "title_content", "blank", "title_slide"],
                            "default": "title_content"
                        }
                    },
                    "required": ["path", "title"]
                }
            ),
            Tool(
                name="create_presentation",
                description="Create a full PowerPoint presentation (.pptx) with multiple slides. Similar to Google Slides or Microsoft PowerPoint.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path where to save the presentation (relative to workspace or absolute). Should end with .pptx"
                        },
                        "title": {
                            "type": "string",
                            "description": "Presentation title"
                        },
                        "slides": {
                            "type": "array",
                            "description": "Array of slide objects, each with 'title' and 'content' fields",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "layout": {
                                        "type": "string",
                                        "enum": ["title_only", "title_content", "blank", "title_slide"],
                                        "default": "title_content"
                                    }
                                },
                                "required": ["title"]
                            }
                        },
                        "author": {
                            "type": "string",
                            "description": "Presentation author (optional)"
                        }
                    },
                    "required": ["path", "title", "slides"]
                }
            ),
        ]
        
        if self.web_search_enabled:
            tools.append(
                Tool(
                    name="web_search",
                    description="Search the web using DuckDuckGo with enhanced features: result caching, relevance scoring, and query optimization. Returns search results with titles, URLs, and snippets.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (will be optimized automatically for better results)"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return (default: 5, max: 20)",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 20
                            },
                            "search_type": {
                                "type": "string",
                                "description": "Type of search: 'text' (default), 'news', or 'images'",
                                "enum": ["text", "news", "images"],
                                "default": "text"
                            }
                        },
                        "required": ["query"]
                    }
                )
            )
        
        return tools
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        Get MCP server information and capabilities
        
        Returns:
            Dictionary containing server metadata including version, capabilities,
            and available tools count
        """
        tools = self.get_tools()
        return {
            "version": self.server_version,
            "capabilities": self.server_capabilities,
            "tool_count": len(tools),
            "tools": [tool.name for tool in tools],
            "workspace_root": self.workspace_root,
            "web_search_enabled": self.web_search_enabled
        }
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], allow_write: bool = True) -> List[TextContent]:
        """
        Execute an MCP tool and return results
        
        This is the core method that implements the MCP protocol's tool execution.
        It routes tool calls from AI models to the appropriate backend services,
        providing real-time access to external systems.
        
        The method:
        1. Validates the tool name and arguments
        2. Routes to the appropriate tool handler
        3. Executes the tool with proper error handling
        4. Returns standardized results in MCP TextContent format
        
        This unified interface allows AI models to access multiple external
        systems (files, web, code analysis) without needing custom integrations
        for each service.
        
        Args:
            tool_name: Name of the tool to execute (must be in get_tools())
            arguments: Tool-specific parameters
            allow_write: Whether write operations are permitted (for ASK mode)
            
        Returns:
            List of TextContent objects with tool execution results
        """
        if not MCP_AVAILABLE:
            logger.error("MCP SDK not available")
            return [TextContent(
                type="text",
                text=f"MCP SDK not available. Please install with: pip install mcp"
            )]
        
        execution_start = time.time()
        logger.info(f"Executing MCP tool: {tool_name} with arguments: {arguments}")
        
        try:
            if tool_name == "read_file":
                return await self._read_file(arguments.get("path", ""))
            elif tool_name == "write_file":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: Write operations are disabled in ASK mode. Switch to Agent mode to modify files."
                    )]
                return await self._write_file(arguments.get("path", ""), arguments.get("content", ""))
            elif tool_name == "list_directory":
                return await self._list_directory(arguments.get("path", "."))
            elif tool_name == "search_files":
                return await self._search_files(arguments.get("query", ""), arguments.get("path", "."))
            elif tool_name == "get_file_tree":
                return await self._get_file_tree(
                    arguments.get("path", "."),
                    arguments.get("max_depth", 4)
                )
            elif tool_name == "analyze_code":
                return await self._analyze_code(arguments.get("path", ""))
            elif tool_name == "grep_code":
                return await self._grep_code(
                    arguments.get("pattern", ""),
                    arguments.get("path", "."),
                    arguments.get("file_extensions", [])
                )
            elif tool_name == "execute_command":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: Command execution is disabled in ASK mode. Switch to Agent mode to run commands."
                    )]
                return await self._execute_command(
                    arguments.get("command", ""),
                    arguments.get("timeout", 30)
                )
            elif tool_name == "web_search":
                return await self._web_search(
                    arguments.get("query", ""),
                    arguments.get("max_results", 5),
                    arguments.get("search_type", "text")
                )
            elif tool_name == "download_file":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: File downloads are disabled in ASK mode. Switch to Agent mode to download files."
                    )]
                return await self._download_file(
                    arguments.get("url", ""),
                    arguments.get("path"),
                    arguments.get("timeout", 60)
                )
            elif tool_name == "create_document":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: Document creation is disabled in ASK mode. Switch to Agent mode to create documents."
                    )]
                return await self._create_document(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                    arguments.get("title", ""),
                    arguments.get("author")
                )
            elif tool_name == "create_slide":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: Slide creation is disabled in ASK mode. Switch to Agent mode to create slides."
                    )]
                return await self._create_slide(
                    arguments.get("path", ""),
                    arguments.get("title", ""),
                    arguments.get("content", ""),
                    arguments.get("layout", "title_content")
                )
            elif tool_name == "create_presentation":
                if not allow_write:
                    return [TextContent(
                        type="text",
                        text="ERROR: Presentation creation is disabled in ASK mode. Switch to Agent mode to create presentations."
                    )]
                return await self._create_presentation(
                    arguments.get("path", ""),
                    arguments.get("title", ""),
                    arguments.get("slides", []),
                    arguments.get("author")
                )
            else:
                execution_time = time.time() - execution_start
                logger.warning(f"Unknown tool requested: {tool_name} (execution time: {execution_time:.3f}s)")
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {tool_name}. Available tools: {', '.join([t.name for t in self.get_tools()])}"
                )]
        except Exception as e:
            execution_time = time.time() - execution_start
            error_msg = f"Error executing {tool_name}: {str(e)}"
            logger.error(f"{error_msg} (execution time: {execution_time:.3f}s)", exc_info=True)
            return [TextContent(
                type="text",
                text=error_msg
            )]
    
    async def _read_file(self, path: str) -> List[TextContent]:
        """Read a file"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            content = await self.file_service.read_file(path)
            return [TextContent(type="text", text=f"File: {path}\n\n{content}")]
        except FileNotFoundError:
            return [TextContent(type="text", text=f"File not found: {path}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error reading file: {str(e)}")]
    
    async def _write_file(self, path: str, content: str) -> List[TextContent]:
        """Write to a file"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            await self.file_service.write_file(path, content)
            self._invalidate_structure_caches()
            return [TextContent(type="text", text=f"Successfully wrote to {path}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error writing file: {str(e)}")]
    
    async def _list_directory(self, path: str) -> List[TextContent]:
        """List directory contents"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            # Normalize path
            if not os.path.isabs(path) or path == ".":
                path = os.path.join(self.workspace_root, path) if path != "." else self.workspace_root

            cache_key = self._build_cache_key(path, "list")
            cached_text = self._get_cached_text(self._dir_cache, cache_key)
            if cached_text:
                return [TextContent(type="text", text=cached_text)]

            files = await self.file_service.list_directory(path)
            file_list = []
            for file_info in files:
                file_type = "DIR" if file_info.is_directory else "FILE"
                size = f"{file_info.size} bytes" if not file_info.is_directory else ""
                file_list.append(f"{file_type:4s} {file_info.name:50s} {size}")
            
            result = f"Directory: {path}\n\n" + "\n".join(file_list)
            self._set_cached_text(self._dir_cache, cache_key, result)
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing directory: {str(e)}")]
    
    async def _search_files(self, query: str, path: str) -> List[TextContent]:
        """Search for files"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            if not os.path.isabs(path) or path == ".":
                path = os.path.join(self.workspace_root, path) if path != "." else self.workspace_root
            
            results = await self.file_service.search_files(query, path)
            if not results:
                return [TextContent(type="text", text=f"No files matching '{query}' were found in {path}.")]

            formatted_results = []
            for entry in results[:20]:
                entry_path = entry.get("path") or entry.get("name") or ""
                info_parts = []
                size_value = entry.get("size")
                if isinstance(size_value, int):
                    info_parts.append(f"{size_value} bytes")
                if entry.get("modified_time"):
                    info_parts.append(f"modified {entry['modified_time']}")
                meta = f" ({'; '.join(info_parts)})" if info_parts else ""
                formatted_results.append(f"- {entry_path}{meta}")

            result = f"Search results for '{query}' in {path}:\n\n" + "\n".join(formatted_results)
            if len(results) > 20:
                result += f"\n... and {len(results) - 20} more results"
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error searching files: {str(e)}")]
    
    async def _get_file_tree(self, path: str, max_depth: int) -> List[TextContent]:
        """Get file tree structure"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            if not os.path.isabs(path) or path == ".":
                path = os.path.join(self.workspace_root, path) if path != "." else self.workspace_root

            cache_key = self._build_cache_key(path, f"tree:{max_depth}")
            cached_text = self._get_cached_text(self._tree_cache, cache_key)
            if cached_text:
                return [TextContent(type="text", text=cached_text)]

            tree = await self.file_service.get_project_structure(path, max_depth=max_depth)
            
            def format_tree(node, indent=0):
                lines = []
                prefix = "  " * indent + ("└── " if indent > 0 else "")
                lines.append(f"{prefix}{node['name']}")
                for child in node.get("children", [])[:20]:  # Limit children
                    lines.extend(format_tree(child, indent + 1))
                return lines
            
            tree_lines = format_tree(tree)
            result = f"File tree for {path}:\n\n" + "\n".join(tree_lines)
            self._set_cached_text(self._tree_cache, cache_key, result)
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error getting file tree: {str(e)}")]
    
    async def _analyze_code(self, path: str) -> List[TextContent]:
        """Analyze code in a file"""
        if not self.code_analyzer:
            return [TextContent(type="text", text="Code analyzer not available")]
        
        try:
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            analysis = await self.code_analyzer.analyze_file(path)
            result = json.dumps(analysis, indent=2)
            return [TextContent(type="text", text=f"Code analysis for {path}:\n\n{result}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error analyzing code: {str(e)}")]
    
    async def _grep_code(self, pattern: str, path: str, file_extensions: List[str]) -> List[TextContent]:
        """Search for patterns in code"""
        if not self.code_analyzer:
            return [TextContent(type="text", text="Code analyzer not available")]
        
        try:
            if not os.path.isabs(path) or path == ".":
                path = os.path.join(self.workspace_root, path) if path != "." else self.workspace_root
            
            # Use code analyzer's grep functionality if available
            # Otherwise, do a simple recursive search
            matches = []
            for root, dirs, files in os.walk(path):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if file_extensions:
                        if not any(file.endswith(ext) for ext in file_extensions):
                            continue
                    
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for line_num, line in enumerate(f, 1):
                                if pattern.lower() in line.lower():
                                    matches.append(f"{file_path}:{line_num}: {line.strip()}")
                    except Exception:
                        continue
                    
                    if len(matches) >= 50:  # Limit results
                        break
                
                if len(matches) >= 50:
                    break
            
            result = f"Grep results for '{pattern}' in {path}:\n\n" + "\n".join(matches[:50])
            if len(matches) > 50:
                result += f"\n... and {len(matches) - 50} more matches"
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error grepping code: {str(e)}")]
    
    async def _execute_command(self, command: str, timeout: int) -> List[TextContent]:
        """
        Execute a shell command with loop prevention.
        
        This method:
        1. Checks for command loops to prevent infinite execution
        2. Executes the command in the workspace directory
        3. Returns formatted output (stdout and stderr) that will be visible in chat
        4. Records the command execution for loop detection
        """
        try:
            # Normalize command for loop detection
            normalized_command = command.strip()
            
            if not normalized_command:
                return [TextContent(
                    type="text",
                    text="ERROR: Command cannot be empty"
                )]
            
            # Check for loops before executing
            is_loop, loop_error = self._check_command_loop(normalized_command)
            if is_loop:
                return [TextContent(
                    type="text",
                    text=loop_error or "LOOP PREVENTION: Command execution blocked to prevent infinite loops"
                )]
            
            # Record command execution (before running, so we track attempts)
            self._record_command_execution(normalized_command)
            
            # Execute the command
            process = await asyncio.create_subprocess_shell(
                normalized_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_root
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                output = stdout.decode('utf-8', errors='ignore') if stdout else ""
                error = stderr.decode('utf-8', errors='ignore') if stderr else ""
                
                # Format result for visibility in chat
                result = f"Command executed: {normalized_command}\n"
                result += f"Working directory: {self.workspace_root}\n"
                result += f"Exit code: {process.returncode}\n\n"
                
                if output:
                    result += f"STDOUT:\n{output}\n"
                if error:
                    result += f"STDERR:\n{error}\n"
                
                # If no output and no error, indicate success
                if not output and not error:
                    result += "Command completed successfully (no output).\n"
                
                self._invalidate_structure_caches()
                return [TextContent(type="text", text=result)]
            except asyncio.TimeoutError:
                process.kill()
                return [TextContent(
                    type="text",
                    text=f"Command timed out after {timeout} seconds: {normalized_command}"
                )]
        except Exception as e:
            logger.exception(f"Error executing command: {command}")
            return [TextContent(
                type="text",
                text=f"Error executing command: {str(e)}"
            )]
    
    async def _download_file(self, url: str, path: Optional[str] = None, timeout: int = 60) -> List[TextContent]:
        """Download a file from a URL and save it to the workspace"""
        if not self.file_service:
            return [TextContent(type="text", text="File service not available")]
        
        try:
            # Validate URL
            parsed_url = urlparse(url)
            if parsed_url.scheme not in ('http', 'https'):
                return [TextContent(type="text", text=f"ERROR: Invalid URL scheme. Only HTTP and HTTPS are supported. Got: {parsed_url.scheme}")]
            
            # Determine save path
            if not path:
                # Extract filename from URL
                filename = os.path.basename(parsed_url.path) or "downloaded_file"
                # Remove query parameters from filename
                if '?' in filename:
                    filename = filename.split('?')[0]
                if not filename or filename == '/':
                    filename = "downloaded_file"
                path = filename
            
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            # Download the file
            logger.info(f"Downloading file from {url} to {path}")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return [TextContent(
                            type="text",
                            text=f"ERROR: Failed to download file. HTTP status: {response.status}"
                        )]
                    
                    # Check content length if available
                    content_length = response.headers.get('Content-Length')
                    if content_length:
                        size_mb = int(content_length) / (1024 * 1024)
                        if size_mb > 100:  # Limit to 100MB
                            return [TextContent(
                                type="text",
                                text=f"ERROR: File too large ({size_mb:.1f}MB). Maximum size is 100MB."
                            )]
                    
                    # Read content in chunks and write to file
                    content = await response.read()
                    
                    # Check size after download
                    size_mb = len(content) / (1024 * 1024)
                    if size_mb > 100:
                        return [TextContent(
                            type="text",
                            text=f"ERROR: Downloaded file too large ({size_mb:.1f}MB). Maximum size is 100MB."
                        )]
                    
                    # Write file
                    async with aiofiles.open(path, 'wb') as f:
                        await f.write(content)
                    
                    self._invalidate_structure_caches()
                    file_size_kb = len(content) / 1024
                    return [TextContent(
                        type="text",
                        text=f"Successfully downloaded file from {url}\nSaved to: {path}\nSize: {file_size_kb:.1f} KB"
                    )]
        except aiohttp.ClientError as e:
            return [TextContent(type="text", text=f"ERROR: Network error downloading file: {str(e)}")]
        except asyncio.TimeoutError:
            return [TextContent(type="text", text=f"ERROR: Download timed out after {timeout} seconds")]
        except Exception as e:
            logger.error(f"Error downloading file: {e}", exc_info=True)
            return [TextContent(type="text", text=f"ERROR: Failed to download file: {str(e)}")]
    
    async def _web_search(self, query: str, max_results: int, search_type: str = "text") -> List[TextContent]:
        """Perform web search using enhanced web search service"""
        try:
            from .web_search_service import WebSearchService
            
            # Use shared web search service instance if available, otherwise create new one
            if hasattr(self, '_web_search_service') and self._web_search_service:
                web_service = self._web_search_service
            else:
                web_service = WebSearchService()
                self._web_search_service = web_service
            
            # Detect if this is a price query - these need fresh, uncached results
            query_lower = query.lower()
            is_price_query = any(keyword in query_lower for keyword in [
                "price", "cost", "value", "worth", "rate", "bitcoin", "btc", "ethereum", "eth",
                "crypto", "stock", "currency", "usd", "eur", "gbp", "jpy", "exchange rate"
            ])
            
            # For price queries, disable cache and increase results to get more sources
            use_cache = not is_price_query  # Don't cache price queries
            
            # Clear any existing cache entries for price queries to ensure fresh results
            if is_price_query and hasattr(web_service, 'cache'):
                # Remove any cached entries that might match this price query
                # This ensures we always get fresh price data
                cache_keys_to_remove = []
                for cache_key in list(web_service.cache.keys()):
                    # Check if this cache key is related to price queries
                    cache_key_lower = cache_key.lower()
                    if any(term in cache_key_lower for term in [
                        "price", "bitcoin", "btc", "ethereum", "eth", "crypto", 
                        "stock", "currency", "exchange rate", "current", "live"
                    ]):
                        cache_keys_to_remove.append(cache_key)
                for key in cache_keys_to_remove:
                    web_service.cache.pop(key, None)
                # Also clear the cache file if it exists
                if hasattr(web_service, 'clear_cache'):
                    # Don't clear all cache, just price-related entries
                    pass
            
            search_max_results = max_results * 2 if is_price_query else max_results  # Get more results for prices
            
            # Optimize query for price queries to get current data
            if is_price_query:
                # Add "current" or "live" if not already present
                optimized_query = query
                if "current" not in query_lower and "live" not in query_lower and "today" not in query_lower:
                    optimized_query = f"current {query}"
                else:
                    optimized_query = query
            else:
                optimized_query = query
            
            # Perform search with enhanced features
            results, metadata = await web_service.search(
                query=optimized_query,
                max_results=min(search_max_results, 20),  # Cap at 20
                search_type=search_type,
                use_cache=use_cache,
                optimize_query=not is_price_query  # Don't optimize further if we already optimized
            )
            
            if metadata.get("error"):
                return [TextContent(type="text", text=f"Search error: {metadata['error']}")]
            
            # For price queries, prioritize results from reputable sources
            if is_price_query and results:
                # Re-sort to prioritize exchanges and financial sites
                def price_source_priority(result):
                    url = (result.get("href") or result.get("url") or "").lower()
                    title = (result.get("title") or "").lower()
                    body = (result.get("body") or result.get("description") or "").lower()
                    
                    priority = 0
                    # High priority sources
                    if any(domain in url for domain in [
                        "coinbase", "binance", "kraken", "gemini", "bitstamp", 
                        "coindesk", "cointelegraph", "bloomberg", "reuters",
                        "yahoo finance", "marketwatch", "nasdaq", "investing.com"
                    ]):
                        priority += 10
                    # Medium priority
                    elif any(domain in url for domain in [
                        "cryptocurrency", "crypto", "exchange", "trading"
                    ]):
                        priority += 5
                    # Check for price indicators in title/body
                    if any(indicator in title or indicator in body for indicator in [
                        "$", "usd", "eur", "price", "current", "live", "now"
                    ]):
                        priority += 3
                    
                    return priority
                
                # Sort by priority (highest first)
                results.sort(key=price_source_priority, reverse=True)
            
            # Format results
            formatted = web_service.format_results(results, optimized_query, include_metadata=True)
            
            # Add metadata info if cached (but price queries shouldn't be cached)
            if metadata.get("cached") and not is_price_query:
                cache_age = metadata.get("cache_age_seconds", 0)
                formatted += f"\n\n[Note: Results from cache, age: {cache_age}s]"
            elif is_price_query:
                formatted += f"\n\n[Note: Fresh search results for current price data]"
            
            return [TextContent(type="text", text=formatted)]
        except ImportError:
            return [TextContent(type="text", text="Web search not available. Install the 'ddgs' package.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error performing web search: {str(e)}")]
    
    async def _create_document(self, path: str, content: str, title: str = "", author: Optional[str] = None) -> List[TextContent]:
        """Create a Word document (.docx)"""
        try:
            try:
                from docx import Document
                from docx.shared import Inches, Pt
                from docx.enum.text import WD_ALIGN_PARAGRAPH
            except ImportError:
                return [TextContent(
                    type="text",
                    text="ERROR: python-docx package not installed. Install it with: pip install python-docx"
                )]
            
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            # Ensure .docx extension
            if not path.lower().endswith('.docx'):
                path += '.docx'
            
            # Create directory if needed
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            # Create document
            doc = Document()
            
            # Set document properties
            if title:
                doc.core_properties.title = title
            if author:
                doc.core_properties.author = author or "AI Agent"
            
            # Add title if provided
            if title:
                title_para = doc.add_heading(title, 0)
                title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Parse content and add to document
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    doc.add_paragraph()  # Empty paragraph for spacing
                    continue
                
                # Handle markdown-style formatting
                if line.startswith('# '):
                    # Heading 1
                    doc.add_heading(line[2:], level=1)
                elif line.startswith('## '):
                    # Heading 2
                    doc.add_heading(line[3:], level=2)
                elif line.startswith('### '):
                    # Heading 3
                    doc.add_heading(line[4:], level=3)
                elif line.startswith('- ') or line.startswith('* '):
                    # Bullet list
                    para = doc.add_paragraph(line[2:], style='List Bullet')
                elif line.startswith('1. ') or line.startswith('1) '):
                    # Numbered list
                    para = doc.add_paragraph(line[3:], style='List Number')
                else:
                    # Regular paragraph
                    para = doc.add_paragraph()
                    # Handle bold and italic
                    text = line
                    # Simple bold/italic handling
                    parts = text.split('**')
                    for i, part in enumerate(parts):
                        if i % 2 == 0:
                            # Regular text
                            para.add_run(part)
                        else:
                            # Bold text
                            para.add_run(part).bold = True
                    
                    # If no bold markers, check for italic
                    if '**' not in text:
                        parts = text.split('*')
                        for i, part in enumerate(parts):
                            if i % 2 == 0:
                                para.add_run(part)
                            else:
                                para.add_run(part).italic = True
            
            # Save document
            doc.save(path)
            self._invalidate_structure_caches()
            
            return [TextContent(
                type="text",
                text=f"Successfully created document: {path}\nTitle: {title or 'Untitled'}\nContent length: {len(content)} characters"
            )]
        except Exception as e:
            logger.error(f"Error creating document: {e}", exc_info=True)
            return [TextContent(type="text", text=f"ERROR: Failed to create document: {str(e)}")]
    
    async def _create_slide(self, path: str, title: str, content: str = "", layout: str = "title_content") -> List[TextContent]:
        """Create a PowerPoint slide"""
        try:
            try:
                from pptx import Presentation
                from pptx.util import Inches, Pt
            except ImportError:
                return [TextContent(
                    type="text",
                    text="ERROR: python-pptx package not installed. Install it with: pip install python-pptx"
                )]
            
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            # Ensure .pptx extension
            if not path.lower().endswith('.pptx'):
                path += '.pptx'
            
            # Create directory if needed
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            # Create or load presentation
            if os.path.exists(path):
                prs = Presentation(path)
            else:
                prs = Presentation()
            
            # Map layout names to slide layout indices
            layout_map = {
                "title_slide": 0,
                "title_content": 1,
                "title_only": 5,
                "blank": 6
            }
            layout_idx = layout_map.get(layout, 1)  # Default to title_content
            
            # Add slide
            slide_layout = prs.slide_layouts[layout_idx]
            slide = prs.slides.add_slide(slide_layout)
            
            # Set title
            if slide.shapes.title:
                slide.shapes.title.text = title
            
            # Set content if available
            if content and hasattr(slide_layout, 'placeholders'):
                # Try to find content placeholder
                for shape in slide.placeholders:
                    if shape.placeholder_format.idx == 1 and shape != slide.shapes.title:
                        shape.text = content
                        break
                else:
                    # If no content placeholder, add text box
                    left = Inches(0.5)
                    top = Inches(2)
                    width = Inches(9)
                    height = Inches(4.5)
                    text_box = slide.shapes.add_textbox(left, top, width, height)
                    text_frame = text_box.text_frame
                    text_frame.text = content
            
            # Save presentation
            prs.save(path)
            self._invalidate_structure_caches()
            
            return [TextContent(
                type="text",
                text=f"Successfully created/updated slide: {path}\nTitle: {title}\nLayout: {layout}"
            )]
        except Exception as e:
            logger.error(f"Error creating slide: {e}", exc_info=True)
            return [TextContent(type="text", text=f"ERROR: Failed to create slide: {str(e)}")]
    
    async def _create_presentation(self, path: str, title: str, slides: List[Dict[str, Any]], author: Optional[str] = None) -> List[TextContent]:
        """Create a full PowerPoint presentation"""
        try:
            try:
                from pptx import Presentation
                from pptx.util import Inches, Pt
            except ImportError:
                return [TextContent(
                    type="text",
                    text="ERROR: python-pptx package not installed. Install it with: pip install python-pptx"
                )]
            
            # Normalize path
            if not os.path.isabs(path):
                path = os.path.join(self.workspace_root, path)
            
            # Ensure .pptx extension
            if not path.lower().endswith('.pptx'):
                path += '.pptx'
            
            # Create directory if needed
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            # Create presentation
            prs = Presentation()
            
            # Set presentation properties
            if title:
                prs.core_properties.title = title
            if author:
                prs.core_properties.author = author or "AI Agent"
            
            # Add title slide
            title_slide_layout = prs.slide_layouts[0]
            title_slide = prs.slides.add_slide(title_slide_layout)
            if title_slide.shapes.title:
                title_slide.shapes.title.text = title
            
            # Add content slides
            layout_map = {
                "title_slide": 0,
                "title_content": 1,
                "title_only": 5,
                "blank": 6
            }
            
            for slide_data in slides:
                slide_title = slide_data.get("title", "")
                slide_content = slide_data.get("content", "")
                slide_layout_name = slide_data.get("layout", "title_content")
                layout_idx = layout_map.get(slide_layout_name, 1)
                
                slide_layout = prs.slide_layouts[layout_idx]
                slide = prs.slides.add_slide(slide_layout)
                
                # Set title
                if slide.shapes.title:
                    slide.shapes.title.text = slide_title
                
                # Set content
                if slide_content:
                    for shape in slide.placeholders:
                        if shape.placeholder_format.idx == 1 and shape != slide.shapes.title:
                            shape.text = slide_content
                            break
                    else:
                        # Add text box if no content placeholder
                        left = Inches(0.5)
                        top = Inches(2)
                        width = Inches(9)
                        height = Inches(4.5)
                        text_box = slide.shapes.add_textbox(left, top, width, height)
                        text_frame = text_box.text_frame
                        text_frame.text = slide_content
            
            # Save presentation
            prs.save(path)
            self._invalidate_structure_caches()
            
            return [TextContent(
                type="text",
                text=f"Successfully created presentation: {path}\nTitle: {title}\nSlides: {len(slides) + 1} (including title slide)"
            )]
        except Exception as e:
            logger.error(f"Error creating presentation: {e}", exc_info=True)
            return [TextContent(type="text", text=f"ERROR: Failed to create presentation: {str(e)}")]


def create_mcp_server(file_service=None, code_analyzer=None, web_search_enabled=True):
    """
    Create and configure an MCP server instance following the Model Context Protocol
    
    This function creates a fully compliant MCP server that implements the
    standardized protocol for AI model integration. The server acts as a bridge
    between AI models and external systems, providing:
    
    - Unified Connectivity: Single interface for all tools and data sources
    - Real-Time Access: Live data retrieval instead of static training data
    - Scalability: Minimal setup, extensible architecture
    - Protocol Compliance: Follows MCP standard for maximum compatibility
    
    The server can be used in two modes:
    1. Direct integration (current): Tools accessed via MCPServerTools class
    2. Standalone server: Can run as separate process using stdio_server
    
    Example use case:
    Instead of writing separate integrations for Notion, Google Sheets, and
    project management tools, connect them all through this MCP server.
    The AI then queries the server, which fetches data and delivers it in real time.
    
    Args:
        file_service: Service for file operations
        code_analyzer: Service for code analysis
        web_search_enabled: Whether to enable web search tool
        
    Returns:
        Tuple of (Server instance, MCPServerTools instance) or (None, None) if MCP unavailable
    """
    if not MCP_AVAILABLE:
        return None
    
    tools = MCPServerTools(file_service, code_analyzer, web_search_enabled)
    server = Server("ai-agent-mcp")
    
    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return tools.get_tools()
    
    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        # Determine if write operations are allowed based on context
        # This will be set by the MCP client wrapper
        allow_write = arguments.pop("_allow_write", True)
        return await tools.execute_tool(name, arguments, allow_write=allow_write)
    
    return server, tools

