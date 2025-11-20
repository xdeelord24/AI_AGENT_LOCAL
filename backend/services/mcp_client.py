"""
MCP Client Wrapper for AI Service
Integrates MCP tools into AI model interactions
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from .mcp_server import MCPServerTools, MCP_AVAILABLE


class MCPClient:
    """MCP Client wrapper for AI service integration"""
    
    def __init__(self, mcp_tools: Optional[MCPServerTools] = None):
        self.mcp_tools = mcp_tools
        self.tool_call_history: List[Dict[str, Any]] = []
    
    def is_available(self) -> bool:
        """Check if MCP is available and configured"""
        return MCP_AVAILABLE and self.mcp_tools is not None
    
    def get_tools_description(self) -> str:
        """Get a formatted description of available MCP tools for prompt building"""
        if not self.is_available():
            return ""
        
        tools = self.mcp_tools.get_tools()
        if not tools:
            return ""
        
        tool_descriptions = []
        tool_descriptions.append("Available MCP Tools:")
        tool_descriptions.append("You can use these tools by including tool calls in your response.")
        tool_descriptions.append("Format: <tool_call name=\"tool_name\" args=\"{...}\" />")
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
                        tool_descriptions.append(f"    - {param_name} ({param_type}): {param_desc}{req_marker}")
            
            tool_descriptions.append("")
        
        return "\n".join(tool_descriptions)
    
    def parse_tool_calls_from_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse tool calls from AI model response"""
        tool_calls = []
        
        # Pattern 1: XML-style tool calls
        # <tool_call name="tool_name" args="{...}" />
        xml_pattern = r'<tool_call\s+name=["\']([^"\']+)["\']\s+args=["\']({[^"\']*})["\']\s*/>'
        for match in re.finditer(xml_pattern, response):
            tool_name = match.group(1)
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                # Try to fix common JSON issues
                args_str = match.group(2).replace("'", '"')
                try:
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
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                continue
            
            tool_calls.append({
                "name": tool_name,
                "arguments": args,
                "raw": match.group(0)
            })
        
        return tool_calls
    
    async def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        allow_write: bool = True
    ) -> List[Dict[str, Any]]:
        """Execute a list of tool calls and return results"""
        if not self.is_available():
            return [{
                "tool": call.get("name", "unknown"),
                "result": "MCP tools not available",
                "error": True
            } for call in tool_calls]
        
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            arguments = tool_call.get("arguments", {})
            
            if not tool_name:
                continue
            
            try:
                # Execute the tool
                tool_results = await self.mcp_tools.execute_tool(
                    tool_name,
                    arguments,
                    allow_write=allow_write
                )
                
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
                
                # Record in history
                self.tool_call_history.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result_text,
                    "error": False
                })
                
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result_text,
                    "error": False
                })
            except Exception as e:
                error_msg = str(e)
                self.tool_call_history.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": error_msg,
                    "error": True
                })
                results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": error_msg,
                    "error": True
                })
        
        return results
    
    def format_tool_results_for_prompt(self, tool_results: List[Dict[str, Any]]) -> str:
        """Format tool execution results for inclusion in AI prompt"""
        if not tool_results:
            return ""
        
        formatted = ["Tool Execution Results:"]
        for result in tool_results:
            tool_name = result.get("tool", "unknown")
            is_error = result.get("error", False)
            result_text = result.get("result", "")
            
            status = "ERROR" if is_error else "SUCCESS"
            formatted.append(f"\n[{status}] {tool_name}:")
            formatted.append(result_text)
        
        formatted.append("")
        formatted.append("Use these results to inform your response.")
        formatted.append("")
        
        return "\n".join(formatted)
    
    def get_recent_tool_calls(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent tool call history"""
        return self.tool_call_history[-limit:]
    
    def clear_history(self):
        """Clear tool call history"""
        self.tool_call_history = []

