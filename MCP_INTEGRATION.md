# MCP (Model Context Protocol) Integration

This AI Agent now includes support for the Model Context Protocol (MCP), which enhances performance by providing standardized tool access and context management.

## What is MCP?

The Model Context Protocol (MCP) is a standardized interface that allows AI models to:
- Access external tools and data sources
- Execute actions through structured tool calls
- Maintain context across interactions
- Improve performance through better context management

## Features Enabled by MCP

### Available Tools

1. **File Operations**
   - `read_file`: Read file contents
   - `write_file`: Write/update files (disabled in ASK mode)
   - `list_directory`: List directory contents
   - `search_files`: Search for files by name pattern
   - `get_file_tree`: Get directory tree structure

2. **Code Analysis**
   - `analyze_code`: Analyze code structure (functions, classes, imports)
   - `grep_code`: Search for patterns in code files

3. **Web Search** (if enabled)
   - `web_search`: Perform web searches using DuckDuckGo

4. **Command Execution**
   - `execute_command`: Execute shell commands (disabled in ASK mode)

## Installation

### Option 1: Using Official MCP SDK (Recommended)

The MCP Python SDK can be installed from the official repository:

```bash
# Install from GitHub (when available)
pip install git+https://github.com/modelcontextprotocol/python-sdk.git

# Or install from PyPI (when published)
pip install mcp
```

### Option 2: Using Custom Implementation (Current)

The current implementation includes a custom MCP-compatible server that works without the official SDK. This allows MCP features to work immediately.

To enable MCP tools, simply ensure the dependencies are installed:

```bash
pip install -r requirements.txt
```

## Configuration

MCP is enabled by default. You can control it via environment variables:

```bash
# Enable/disable MCP (default: true)
export ENABLE_MCP=true

# Enable/disable web search tools (default: true)
export ENABLE_WEB_SEARCH=true
```

## How It Works

### 1. Tool Discovery

When MCP is enabled, the AI model receives a list of available tools in the prompt:

```
MCP TOOLS AVAILABLE:
====================

Tool: read_file
  Description: Read the contents of a file...
  Parameters:
    - path (string): Path to the file to read (required)
...
```

### 2. Tool Calls

The AI model can make tool calls in its response using this format:

```xml
<tool_call name="read_file" args='{"path": "example.py"}' />
```

### 3. Tool Execution

The MCP client automatically:
1. Parses tool calls from the AI response
2. Executes the tools with the provided arguments
3. Returns results to the AI model for a follow-up response

### 4. Context Integration

Tool execution results are automatically included in the AI's context, allowing it to:
- Use real file contents in responses
- Perform actual operations (file reads, code analysis, etc.)
- Provide more accurate and actionable answers

## Mode-Specific Behavior

### ASK Mode (Read-Only)
- Read operations: ✅ Enabled
- Write operations: ❌ Disabled (tools return errors)
- Command execution: ❌ Disabled
- Tool calls are still parsed and executed, but write operations are blocked

### Agent/Plan Mode
- All operations: ✅ Enabled
- Tools can modify files, execute commands, etc.
- Full MCP functionality available

## Example Usage

### AI Request
```
"Read the contents of main.py and explain what it does"
```

### Tool Call Generated
```xml
<tool_call name="read_file" args='{"path": "main.py"}' />
```

### Tool Execution Result
```
File: main.py

#!/usr/bin/env python3
...
[file contents]
...
```

### AI Response
```
Looking at main.py, this is the main entry point for the application...
[detailed explanation based on actual file contents]
```

## Benefits

1. **Improved Accuracy**: AI responses are based on actual file contents and operations
2. **Better Context**: Tools provide real-time information about the codebase
3. **Actionable Results**: AI can perform actual operations, not just describe them
4. **Standardized Interface**: MCP provides a consistent way to interact with tools
5. **Extensible**: Easy to add new tools following the MCP protocol

## Adding Custom Tools

To add custom MCP tools:

1. Add the tool definition in `backend/services/mcp_server.py`:

```python
Tool(
    name="custom_tool",
    description="Description of your tool",
    inputSchema={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "Parameter description"}
        },
        "required": ["param"]
    }
)
```

2. Add the tool execution handler:

```python
async def _custom_tool(self, param: str) -> List[TextContent]:
    # Your tool logic here
    return [TextContent(type="text", text="Result")]
```

3. Register the tool in `execute_tool()`:

```python
elif tool_name == "custom_tool":
    return await self._custom_tool(arguments.get("param", ""))
```

## Troubleshooting

### MCP Tools Not Available

If MCP tools are not showing up:
1. Check that MCP is enabled: `ENABLE_MCP=true`
2. Verify services are initialized in `main.py`
3. Check console logs for initialization errors

### Tool Execution Errors

If tools are failing:
1. Check file permissions
2. Verify paths are correct (relative to workspace root)
3. Review error messages in tool execution results

### Performance Considerations

- Tool execution adds latency to AI responses
- Multiple tool calls increase response time
- Consider batching related operations

## Future Enhancements

- Support for streaming tool results
- Tool result caching
- Tool usage analytics
- Integration with external MCP servers
- More advanced tool orchestration

## Resources

- [MCP Specification](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Documentation](https://modelcontextprotocol.io/docs)

