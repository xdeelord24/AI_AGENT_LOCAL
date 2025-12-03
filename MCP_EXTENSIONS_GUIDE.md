# MCP Extensions Usage Guide

## Overview

MCP (Model Context Protocol) extensions allow you to extend the capabilities of your AI agent by adding external tools and services. When you install an MCP extension, it becomes available for the AI to use during conversations.

## How MCP Extensions Work

1. **Installation**: When you install an extension from the Extensions marketplace, it's registered in your system.
2. **Configuration**: The extension needs to be configured in your MCP configuration file.
3. **Activation**: After configuration and restart, the extension's tools become available to the AI.

## Using Installed Extensions

### Step 1: Check Installed Extensions

1. Open the **Extensions** tab in the left sidebar
2. Filter by "Installed" to see your installed extensions
3. Click on an extension to view its details and usage instructions

### Step 2: Configure the Extension

Each MCP extension requires configuration. The configuration file is located at:
- **Default**: `~/.ai_agent/mcp_config.json`
- **Custom**: Set via `AI_AGENT_CONFIG_DIR` environment variable

#### Example Configuration Format

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token_here"
      }
    },
    "postgres": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server_postgres"],
      "env": {
        "POSTGRES_CONNECTION_STRING": "postgresql://user:password@localhost:5432/dbname"
      }
    }
  }
}
```

### Step 3: Install Required Dependencies

Before using an extension, make sure you have the required dependencies:

- **Node.js extensions**: Requires Node.js and npm/npx
- **Python extensions**: Requires Python and pip
- **System extensions**: May require system-level dependencies

Check the extension's repository for specific requirements.

### Step 4: Set Up Credentials

Most extensions require API keys or credentials:

1. Get your API key from the service provider
2. Add it to your environment variables or the MCP config file
3. Never commit credentials to version control

### Step 5: Restart the Backend

After configuring an extension:

1. Stop the backend server (Ctrl+C)
2. Restart it: `python main.py`
3. Check the startup logs for "✅ MCP tools enabled and available"

### Step 6: Use in Chat

Once configured and restarted, the extension's tools are automatically available:

- The AI will automatically use the tools when appropriate
- You don't need to explicitly call them
- The AI will use them based on your requests

## Popular Extensions

### GitHub MCP Server
- **Use case**: Access GitHub repositories, issues, pull requests
- **Setup**: Requires GitHub Personal Access Token
- **Example**: "Show me the latest issues in my repository"

### Postgres Context Server
- **Use case**: Query PostgreSQL databases
- **Setup**: Requires database connection string
- **Example**: "Query the users table and show me the results"

### Brave Search MCP Server
- **Use case**: Enhanced web search capabilities
- **Setup**: Requires Brave Search API key
- **Example**: "Search for the latest Python best practices"

## Troubleshooting

### Extension Not Working

1. **Check installation**: Verify the extension is installed in the Extensions tab
2. **Check configuration**: Ensure the MCP config file is properly formatted
3. **Check dependencies**: Make sure all required dependencies are installed
4. **Check logs**: Look for error messages in the backend console
5. **Check credentials**: Verify API keys and credentials are correct

### Common Issues

- **"MCP tools not available"**: Install the MCP Python package: `pip install mcp`
- **"Extension not found"**: Restart the backend after installation
- **"Permission denied"**: Check file permissions on the config directory
- **"Connection failed"**: Verify the extension's server is running and accessible

## Extension Development

To create your own MCP extension:

1. Follow the [MCP Protocol Specification](https://modelcontextprotocol.io)
2. Implement the MCP server interface
3. Publish to npm, PyPI, or your preferred package registry
4. Submit to the Extensions marketplace

## Getting Help

- Check the extension's repository for documentation
- Review the MCP protocol documentation
- Check backend logs for error messages
- Open an issue on the extension's repository

## Security Notes

- Never commit API keys or credentials to version control
- Use environment variables for sensitive data
- Regularly rotate API keys
- Review extension permissions before installation
- Only install extensions from trusted sources

