"""
MCP Server Implementation for AI Agent
Provides tools for file operations, code analysis, web search, and more
"""

import asyncio
import json
import os
import subprocess
from typing import Any, Dict, List, Optional
from pathlib import Path

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
    """MCP Server Tools for AI Agent operations"""
    
    def __init__(self, file_service=None, code_analyzer=None, web_search_enabled=True):
        self.file_service = file_service
        self.code_analyzer = code_analyzer
        self.web_search_enabled = web_search_enabled
        self.workspace_root = os.getcwd()
    
    def get_tools(self) -> List[Tool]:
        """Get list of available MCP tools"""
        if not MCP_AVAILABLE:
            return []
        
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
                description="Execute a shell command in the workspace directory. Use with caution in production.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute"
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
        ]
        
        if self.web_search_enabled:
            tools.append(
                Tool(
                    name="web_search",
                    description="Search the web using DuckDuckGo. Returns search results with titles, URLs, and snippets.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return (default: 5)",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                )
            )
        
        return tools
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], allow_write: bool = True) -> List[TextContent]:
        """Execute an MCP tool and return results"""
        if not MCP_AVAILABLE:
            return [TextContent(
                type="text",
                text=f"MCP SDK not available. Please install with: pip install mcp"
            )]
        
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
                    arguments.get("max_results", 5)
                )
            else:
                return [TextContent(
                    type="text",
                    text=f"Unknown tool: {tool_name}"
                )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error executing {tool_name}: {str(e)}"
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
            
            files = await self.file_service.list_directory(path)
            file_list = []
            for file_info in files:
                file_type = "DIR" if file_info.is_directory else "FILE"
                size = f"{file_info.size} bytes" if not file_info.is_directory else ""
                file_list.append(f"{file_type:4s} {file_info.name:50s} {size}")
            
            result = f"Directory: {path}\n\n" + "\n".join(file_list)
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
            result_list = [f"- {r}" for r in results[:20]]  # Limit to 20 results
            result = f"Search results for '{query}' in {path}:\n\n" + "\n".join(result_list)
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
        """Execute a shell command"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
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
                
                result = f"Command: {command}\n"
                result += f"Exit code: {process.returncode}\n\n"
                if output:
                    result += f"STDOUT:\n{output}\n"
                if error:
                    result += f"STDERR:\n{error}\n"
                
                return [TextContent(type="text", text=result)]
            except asyncio.TimeoutError:
                process.kill()
                return [TextContent(
                    type="text",
                    text=f"Command timed out after {timeout} seconds: {command}"
                )]
        except Exception as e:
            return [TextContent(type="text", text=f"Error executing command: {str(e)}")]
    
    async def _web_search(self, query: str, max_results: int) -> List[TextContent]:
        """Perform web search"""
        try:
            from duckduckgo_search import DDGS
            
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            
            result_lines = [f"Web search results for '{query}':\n"]
            for idx, r in enumerate(results, 1):
                result_lines.append(f"{idx}. {r.get('title', 'No title')}")
                result_lines.append(f"   URL: {r.get('href', r.get('url', 'N/A'))}")
                result_lines.append(f"   {r.get('body', r.get('description', 'No description'))}")
                result_lines.append("")
            
            return [TextContent(type="text", text="\n".join(result_lines))]
        except ImportError:
            return [TextContent(type="text", text="Web search not available. Install duckduckgo-search package.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error performing web search: {str(e)}")]


def create_mcp_server(file_service=None, code_analyzer=None, web_search_enabled=True):
    """Create and configure an MCP server instance"""
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

