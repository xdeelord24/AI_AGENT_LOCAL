"""
Model Context Protocol (MCP) Client Wrapper for AI Service

The MCP Client acts as the communication layer between AI models and the MCP Server,
implementing the client-side of the Model Context Protocol.

Key Responsibilities:
- Parse tool calls from AI model responses
- Execute tools through the MCP server
- Format tool results for AI consumption
- Maintain tool call history for debugging and analytics

This client enables AI models to:
1. Discover available tools through standardized descriptions
2. Make tool calls in a standardized format
3. Receive real-time results from external systems
4. Access multiple data sources through one unified interface

The MCP Client implements the protocol's client-side requirements, ensuring
seamless communication with any MCP-compliant server.
"""

import json
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from .mcp_server import MCPServerTools, MCP_AVAILABLE

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP Client - Communication layer between AI models and MCP Server
    
    This class implements the client-side of the Model Context Protocol,
    providing a standardized way for AI models to interact with external
    tools and data sources through the MCP server.
    
    The client provides:
    - Tool discovery: Get descriptions of available tools
    - Tool call parsing: Extract tool calls from AI responses
    - Tool execution: Route tool calls to the MCP server
    - Result formatting: Convert tool results for AI consumption
    
    This unified interface removes the need for custom integrations for
    each external service, making AI assistants more useful by giving them
    access to live, accurate information.
    """
    
    def __init__(self, mcp_tools: Optional[MCPServerTools] = None):
        self.mcp_tools = mcp_tools
        self.tool_call_history: List[Dict[str, Any]] = []
        # Analytics: track tool usage statistics
        self.tool_usage_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "count": 0,
            "success_count": 0,
            "error_count": 0,
            "total_time": 0.0,
            "avg_time": 0.0,
            "last_used": None
        })
    
    def is_available(self) -> bool:
        """Check if MCP is available and configured"""
        # If mcp_tools is set, MCP is available regardless of module-level MCP_AVAILABLE
        # This allows MCP to work even if the import had issues, as long as tools were provided
        return self.mcp_tools is not None
    
    def get_tools_description(self) -> str:
        """
        Get a formatted description of available MCP tools for prompt building
        
        Returns a comprehensive description including:
        - Tool names and descriptions
        - Parameter schemas with types and requirements
        - Usage examples where applicable
        """
        if not self.is_available():
            return ""
        
        tools = self.mcp_tools.get_tools()
        if not tools:
            return ""
        
        tool_descriptions = []
        tool_descriptions.append("=" * 80)
        tool_descriptions.append("Available MCP Tools")
        tool_descriptions.append("=" * 80)
        tool_descriptions.append("")
        tool_descriptions.append("You can use these tools by including tool calls in your response.")
        tool_descriptions.append("Format: <tool_call name=\"tool_name\" args=\"{...}\" />")
        tool_descriptions.append("")
        tool_descriptions.append("⚠️ IMPORTANT: `file_operations` is NOT a tool - it is metadata format for your response JSON.")
        tool_descriptions.append("- Use the tools below (write_file, read_file, etc.) for actual file operations.")
        tool_descriptions.append("- Include `file_operations` array in your JSON metadata response to tell the IDE what files to create/edit/delete.")
        tool_descriptions.append("- NEVER call `file_operations` as a tool - it does not exist as a tool.")
        tool_descriptions.append("")
        tool_descriptions.append("📄 DOCUMENT FILES (Office/Research Mode):")
        tool_descriptions.append("- Tools like create_document, create_slide, create_presentation create BINARY files (.docx, .pptx).")
        tool_descriptions.append("- These files are NOT text files and should NOT be created via file_operations.")
        tool_descriptions.append("- These tools handle the binary file creation directly - just call the tool, don't create file_operations.")
        tool_descriptions.append("- Binary document files will NOT be opened in the code editor (they're not editable as text).")
        tool_descriptions.append("")
        
        # Add server info if available
        if hasattr(self.mcp_tools, 'get_server_info'):
            server_info = self.mcp_tools.get_server_info()
            tool_descriptions.append(f"MCP Server Version: {server_info.get('version', 'unknown')}")
            tool_descriptions.append(f"Total Tools Available: {server_info.get('tool_count', len(tools))}")
            tool_descriptions.append("")
        
        for tool in tools:
            tool_descriptions.append(f"Tool: {tool.name}")
            tool_descriptions.append(f"  Description: {tool.description}")
            
            # Extract schema information
            if hasattr(tool, 'inputSchema') and tool.inputSchema:
                schema = tool.inputSchema
                props = schema.get("properties", {})
                required = schema.get("required", [])
                
                if props:
                    tool_descriptions.append("  Parameters:")
                    for param_name, param_info in props.items():
                        param_type = param_info.get("type", "string")
                        param_desc = param_info.get("description", "")
                        is_required = param_name in required
                        req_marker = " (required)" if is_required else " (optional)"
                        
                        # Add default value if present
                        default = param_info.get("default")
                        default_str = f", default: {default}" if default is not None else ""
                        
                        # Add constraints if present
                        constraints = []
                        if "enum" in param_info:
                            constraints.append(f"enum: {param_info['enum']}")
                        if "minimum" in param_info:
                            constraints.append(f"min: {param_info['minimum']}")
                        if "maximum" in param_info:
                            constraints.append(f"max: {param_info['maximum']}")
                        constraints_str = f" [{', '.join(constraints)}]" if constraints else ""
                        
                        tool_descriptions.append(f"    - {param_name} ({param_type}){req_marker}{default_str}{constraints_str}: {param_desc}")
            
            # Add usage example for common tools
            if tool.name == "web_search":
                tool_descriptions.append("  Example: <tool_call name=\"web_search\" args='{\"query\": \"Python async programming\", \"max_results\": 5}' />")
            elif tool.name == "read_file":
                tool_descriptions.append("  Example: <tool_call name=\"read_file\" args='{\"path\": \"src/main.py\"}' />")
            elif tool.name == "list_directory":
                tool_descriptions.append("  Example: <tool_call name=\"list_directory\" args='{\"path\": \".\"}' />")
            elif tool.name == "identify_image":
                tool_descriptions.append("  Example (when images are attached): <tool_call name=\"identify_image\" args='{\"query\": \"what is in this image?\"}' />")
                tool_descriptions.append("  Example (with explicit image data): <tool_call name=\"identify_image\" args='{\"image_data\": \"data:image/png;base64,...\", \"query\": \"what code is shown?\"}' />")
            
            tool_descriptions.append("")
        
        tool_descriptions.append("=" * 80)
        tool_descriptions.append("")
        
        return "\n".join(tool_descriptions)
    
    def parse_tool_calls_from_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse tool calls from AI model response"""
        tool_calls = []
        
        # Normalize common tool name mistakes
        def normalize_tool_name(name: str) -> str:
            """Normalize tool names to correct format"""
            name = name.strip().lower()
            # Common mistakes - map to correct names
            name_mapping = {
                "writefile": "write_file",
                "readfile": "read_file",
                "deletefile": "delete_file",
                "listdirectory": "list_directory",
                "getfiletree": "get_file_tree",
                "grepcode": "grep_code",
                "executecommand": "execute_command",
                "websearch": "web_search",
            }
            normalized = name_mapping.get(name, name)
            # If not in mapping, try to add underscores between camelCase
            if normalized == name and not '_' in name:
                # Try to detect camelCase and convert: writeFile -> write_file
                import re
                normalized = re.sub(r'([a-z])([A-Z])', r'\1_\2', name).lower()
            return normalized
        
        # Pattern 1: XML-style tool calls (correct format)
        # <tool_call name="tool_name" args="{...}" />
        # Handle both single and double quotes for args attribute, with proper JSON parsing
        # Extract args by finding the opening quote, then matching until the matching closing quote
        # accounting for the fact that JSON inside may contain the opposite quote type
        
        # Find all <tool_call> tags (correct format)
        tag_pattern = r'<tool_call\s+name=(["\'])([^"\']+)\1\s+args=(["\'])(.*?)\3\s*/>'
        for match in re.finditer(tag_pattern, response, re.DOTALL | re.IGNORECASE):
            tool_name = match.group(2)
            tool_name = normalize_tool_name(tool_name)  # Normalize tool name
            args_quote_char = match.group(3)  # The quote character used for args (' or ")
            args_content = match.group(4)  # The JSON content inside the quotes
            
            # Parse the JSON args
            try:
                args = json.loads(args_content)
            except json.JSONDecodeError:
                # Try to fix common JSON issues
                # If args were in single quotes, JSON inside should use double quotes (standard)
                # If args were in double quotes, we need to be more careful
                if args_quote_char == "'":
                    # Args in single quotes, JSON should be standard (double quotes for strings)
                    # Just try parsing as-is first
                    try:
                        args = json.loads(args_content)
                    except json.JSONDecodeError:
                        # Try replacing single quotes with double quotes (for non-standard JSON)
                        args_str = args_content.replace("'", '"')
                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            continue
                else:
                    # Args in double quotes - JSON inside might have escaped quotes
                    try:
                        args = json.loads(args_content)
                    except json.JSONDecodeError:
                        # Try unescaping and reparsing
                        try:
                            # Handle escaped quotes
                            args_str = args_content.replace('\\"', '__TEMP_ESC_DQUOTE__')
                            args_str = args_str.replace('"', "'").replace('__TEMP_ESC_DQUOTE__', '"')
                            args_str = args_str.replace("'", '"')
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            continue
            
            tool_calls.append({
                "name": tool_name,
                "arguments": args,
                "raw": match.group(0)
            })
        
        # Pattern 1b: Handle common mistakes - <toolcall> (no underscore) and missing closing />
        # Also handle <toolcall> without underscore
        tag_pattern_alt = r'<toolcall\s+name=(["\'])([^"\']+)\1\s+args=(["\'])(.*?)\3\s*/?>'
        for match in re.finditer(tag_pattern_alt, response, re.DOTALL | re.IGNORECASE):
            tool_name = match.group(2)
            tool_name = normalize_tool_name(tool_name)  # Normalize tool name
            args_quote_char = match.group(3)
            args_content = match.group(4)
            
            # Parse the JSON args (same logic as above)
            try:
                args = json.loads(args_content)
            except json.JSONDecodeError:
                if args_quote_char == "'":
                    try:
                        args = json.loads(args_content)
                    except json.JSONDecodeError:
                        args_str = args_content.replace("'", '"')
                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            continue
                else:
                    try:
                        args = json.loads(args_content)
                    except json.JSONDecodeError:
                        try:
                            args_str = args_content.replace('\\"', '__TEMP_ESC_DQUOTE__')
                            args_str = args_str.replace('"', "'").replace('__TEMP_ESC_DQUOTE__', '"')
                            args_str = args_str.replace("'", '"')
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            continue
            
            tool_calls.append({
                "name": tool_name,
                "arguments": args,
                "raw": match.group(0)
            })
        
        # Pattern 2: JSON tool call blocks
        # ```json
        # {"tool": "tool_name", "arguments": {...}}
        # ```
        json_block_pattern = r'```(?:json)?\s*(\{[^}]*"tool"[^}]*\}[^`]*)```'
        for match in re.finditer(json_block_pattern, response, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                if "tool" in data or "tool_name" in data:
                    tool_name = data.get("tool") or data.get("tool_name")
                    tool_name = normalize_tool_name(str(tool_name))  # Normalize tool name
                    args = data.get("arguments") or data.get("args") or {}
                    tool_calls.append({
                        "name": tool_name,
                        "arguments": args,
                        "raw": match.group(0)
                    })
            except json.JSONDecodeError:
                continue
        
        # Pattern 3: Function call format (OpenAI-style)
        # function_call("tool_name", {...})
        function_pattern = r'function_call\(["\']([^"\']+)["\'],\s*({[^}]*})\)'
        for match in re.finditer(function_pattern, response):
            tool_name = match.group(1)
            tool_name = normalize_tool_name(tool_name)  # Normalize tool name
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                continue
            
            tool_calls.append({
                "name": tool_name,
                "arguments": args,
                "raw": match.group(0)
            })
        
        # Remove duplicates (same tool name and arguments) - keep first occurrence
        seen = set()
        unique_tool_calls = []
        for tc in tool_calls:
            # Create a key from tool name and sorted arguments
            key = (tc["name"], json.dumps(tc["arguments"], sort_keys=True))
            if key not in seen:
                seen.add(key)
                unique_tool_calls.append(tc)
        
        return unique_tool_calls
    
    async def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        allow_write: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Execute a list of tool calls and return results with enhanced tracking
        
        This method executes multiple tool calls in sequence, tracking performance
        metrics, usage statistics, and providing detailed error reporting.
        """
        if not self.is_available():
            logger.warning(f"MCP not available - is_available()={self.is_available()}, mcp_tools={self.mcp_tools is not None}")
            return [{
                "tool": call.get("name", "unknown"),
                "result": "MCP tools not available",
                "error": True,
                "error_type": "MCP_UNAVAILABLE"
            } for call in tool_calls]
        
        # Check available tools
        available_tools = self.mcp_tools.get_tools() if self.mcp_tools else []
        available_tool_names = [tool.name for tool in available_tools] if available_tools else []
        logger.info(f"[DEBUG] Available MCP tools: {available_tool_names} (count: {len(available_tools)})")
        if not available_tools and self.mcp_tools:
            logger.warning(f"[DEBUG] get_tools() returned empty list, but mcp_tools object exists. MCP_AVAILABLE may be False.")
        
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            arguments = tool_call.get("arguments", {})
            execution_start = time.time()
            
            if not tool_name:
                logger.warning("Tool call missing name, skipping")
                continue
            
            # Validate tool name
            if tool_name not in available_tool_names:
                error_msg = f"Tool '{tool_name}' is not available. Available tools: {available_tool_names}"
                logger.warning(error_msg)
                self._update_tool_stats(tool_name, False, 0.0)
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": error_msg,
                    "error": True,
                    "error_type": "TOOL_NOT_FOUND"
                })
                continue
            
            logger.info(f"Executing tool: {tool_name} with args: {arguments}")
            try:
                # Validate arguments before execution
                validation_error = self._validate_tool_arguments(tool_name, arguments, available_tools)
                if validation_error:
                    raise ValueError(validation_error)
                
                # Execute the tool
                tool_results = await self.mcp_tools.execute_tool(
                    tool_name,
                    arguments,
                    allow_write=allow_write
                )
                
                execution_time = time.time() - execution_start
                logger.debug(f"Tool {tool_name} executed in {execution_time:.3f}s, returned {len(tool_results) if tool_results else 0} result(s)")
                
                # Extract text from results
                result_texts = []
                for result in tool_results:
                    if hasattr(result, 'text'):
                        result_texts.append(result.text)
                    elif isinstance(result, dict):
                        result_texts.append(result.get('text', str(result)))
                    else:
                        result_texts.append(str(result))
                
                result_text = "\n".join(result_texts)
                result_length = len(result_text)
                logger.debug(f"Tool {tool_name} result: {result_length} chars")
                
                # Update statistics
                self._update_tool_stats(tool_name, True, execution_time)
                
                # Record in history with metadata
                history_entry = {
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result_text,
                    "error": False,
                    "execution_time": execution_time,
                    "result_length": result_length,
                    "timestamp": time.time()
                }
                self.tool_call_history.append(history_entry)
                
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result_text,
                    "error": False,
                    "execution_time": execution_time,
                    "result_length": result_length
                })
            except ValueError as ve:
                # Validation error
                execution_time = time.time() - execution_start
                error_msg = f"Invalid arguments: {str(ve)}"
                logger.warning(f"Tool {tool_name} validation error: {error_msg}")
                self._update_tool_stats(tool_name, False, execution_time)
                self._record_error(tool_name, arguments, error_msg, "VALIDATION_ERROR")
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": error_msg,
                    "error": True,
                    "error_type": "VALIDATION_ERROR",
                    "execution_time": execution_time
                })
            except Exception as e:
                execution_time = time.time() - execution_start
                error_msg = str(e)
                logger.error(f"Tool {tool_name} execution error: {error_msg}", exc_info=True)
                self._update_tool_stats(tool_name, False, execution_time)
                self._record_error(tool_name, arguments, error_msg, "EXECUTION_ERROR")
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": f"Error executing {tool_name}: {error_msg}",
                    "error": True,
                    "error_type": "EXECUTION_ERROR",
                    "execution_time": execution_time
                })
        
        return results
    
    def _validate_tool_arguments(self, tool_name: str, arguments: Dict[str, Any], available_tools: List) -> Optional[str]:
        """Validate tool arguments against the tool's schema"""
        # Find the tool definition
        tool_def = None
        for tool in available_tools:
            if tool.name == tool_name:
                tool_def = tool
                break
        
        if not tool_def or not hasattr(tool_def, 'inputSchema'):
            return None  # Can't validate without schema
        
        schema = tool_def.inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Check required fields
        for field in required:
            if field not in arguments:
                return f"Missing required argument: {field}"
        
        # Validate types and constraints
        for field, value in arguments.items():
            if field not in properties:
                # Allow extra fields but warn
                continue
            
            field_schema = properties[field]
            field_type = field_schema.get("type")
            
            # Type validation
            if field_type == "string" and not isinstance(value, str):
                return f"Argument '{field}' must be a string"
            elif field_type == "integer" and not isinstance(value, int):
                return f"Argument '{field}' must be an integer"
            elif field_type == "array" and not isinstance(value, list):
                return f"Argument '{field}' must be an array"
            elif field_type == "object" and not isinstance(value, dict):
                return f"Argument '{field}' must be an object"
            
            # Check constraints
            if field_type == "integer":
                if "minimum" in field_schema and value < field_schema["minimum"]:
                    return f"Argument '{field}' must be >= {field_schema['minimum']}"
                if "maximum" in field_schema and value > field_schema["maximum"]:
                    return f"Argument '{field}' must be <= {field_schema['maximum']}"
            
            if field_type == "string":
                if "enum" in field_schema and value not in field_schema["enum"]:
                    return f"Argument '{field}' must be one of: {field_schema['enum']}"
        
        return None  # Validation passed
    
    def _update_tool_stats(self, tool_name: str, success: bool, execution_time: float):
        """Update tool usage statistics"""
        stats = self.tool_usage_stats[tool_name]
        stats["count"] += 1
        stats["total_time"] += execution_time
        stats["avg_time"] = stats["total_time"] / stats["count"]
        stats["last_used"] = time.time()
        
        if success:
            stats["success_count"] += 1
        else:
            stats["error_count"] += 1
    
    def _record_error(self, tool_name: str, arguments: Dict[str, Any], error_msg: str, error_type: str):
        """Record error in history"""
        self.tool_call_history.append({
            "tool": tool_name,
            "arguments": arguments,
            "result": error_msg,
            "error": True,
            "error_type": error_type,
            "timestamp": time.time()
        })
    
    def format_tool_results_for_prompt(self, tool_results: List[Dict[str, Any]]) -> str:
        """
        Format tool execution results for inclusion in AI prompt with enhanced metadata
        
        Includes execution times, result sizes, and error types for better context.
        """
        if not tool_results:
            return ""
        
        formatted = ["=" * 80]
        formatted.append("TOOL EXECUTION RESULTS")
        formatted.append("=" * 80)
        formatted.append("")
        
        total_execution_time = 0.0
        success_count = 0
        error_count = 0
        
        for result in tool_results:
            tool_name = result.get("tool", "unknown")
            is_error = result.get("error", False)
            result_text = result.get("result", "")
            execution_time = result.get("execution_time", 0.0)
            result_length = result.get("result_length", len(result_text))
            error_type = result.get("error_type", "UNKNOWN")
            
            total_execution_time += execution_time
            if is_error:
                error_count += 1
            else:
                success_count += 1
            
            status = "ERROR" if is_error else "SUCCESS"
            formatted.append(f"[{status}] {tool_name}")
            
            # Add metadata
            if execution_time > 0:
                formatted.append(f"  Execution time: {execution_time:.3f}s")
            if result_length > 0 and not is_error:
                formatted.append(f"  Result size: {result_length} characters")
            if is_error and error_type != "UNKNOWN":
                formatted.append(f"  Error type: {error_type}")
            
            formatted.append("")
            if is_error:
                formatted.append(f"Error: {result_text}")
            else:
                formatted.append(result_text)
            formatted.append("")
        
        # Add summary
        formatted.append("-" * 80)
        formatted.append(f"Summary: {success_count} successful, {error_count} errors, total time: {total_execution_time:.3f}s")
        formatted.append("=" * 80)
        formatted.append("")
        formatted.append("IMPORTANT: The tool execution results above contain the actual data from the tools.")
        formatted.append("You MUST use this information in your response. Do not say you will perform the action - it has already been done.")
        formatted.append("For web_search results, extract the relevant information and provide a direct answer to the user's question.")
        formatted.append("")
        
        return "\n".join(formatted)
    
    def get_recent_tool_calls(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent tool call history"""
        return self.tool_call_history[-limit:]
    
    def get_tool_statistics(self) -> Dict[str, Dict[str, Any]]:
        """
        Get usage statistics for all tools
        
        Returns:
            Dictionary mapping tool names to their usage statistics including:
            - count: Total number of calls
            - success_count: Number of successful calls
            - error_count: Number of failed calls
            - total_time: Total execution time in seconds
            - avg_time: Average execution time in seconds
            - last_used: Timestamp of last use
        """
        return dict(self.tool_usage_stats)
    
    def get_tool_statistics_summary(self) -> str:
        """Get a formatted summary of tool usage statistics"""
        if not self.tool_usage_stats:
            return "No tool usage statistics available."
        
        lines = ["Tool Usage Statistics:", "=" * 60]
        for tool_name, stats in sorted(self.tool_usage_stats.items()):
            success_rate = (stats["success_count"] / stats["count"] * 100) if stats["count"] > 0 else 0
            lines.append(f"\n{tool_name}:")
            lines.append(f"  Total calls: {stats['count']}")
            lines.append(f"  Success: {stats['success_count']} ({success_rate:.1f}%)")
            lines.append(f"  Errors: {stats['error_count']}")
            lines.append(f"  Avg time: {stats['avg_time']:.3f}s")
            if stats["last_used"]:
                from datetime import datetime
                last_used_dt = datetime.fromtimestamp(stats["last_used"])
                lines.append(f"  Last used: {last_used_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def clear_history(self):
        """Clear tool call history and reset statistics"""
        self.tool_call_history = []
        self.tool_usage_stats.clear()
    
    def remove_tool_calls_from_text(self, text: str) -> str:
        """Remove tool call tags from text, leaving clean response"""
        if not text:
            return text
        
        # Remove XML-style tool calls: <tool_call name="..." args="..." />
        # Handle both single and double quotes
        text = re.sub(r'<tool_call\s+name=["\'][^"\']+["\']\s+args=["\'][^"\']*["\']\s*/>', '', text, flags=re.DOTALL)
        
        # Also remove any closing tool_call tags that might be separate
        text = re.sub(r'</tool_call>', '', text)
        
        # Clean up any extra whitespace left behind
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple newlines to double
        text = text.strip()
        
        return text

