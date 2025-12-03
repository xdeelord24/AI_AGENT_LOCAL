# VSCode/Cursor Extensions Integration Guide

## Overview

The AI Agent Local system now supports browsing and installing extensions from the VSCode Marketplace, in addition to MCP (Model Context Protocol) server extensions. This allows you to access thousands of extensions including themes, language support, snippets, debuggers, formatters, and more.

## Features

### Extension Sources

1. **MCP Servers** - Model Context Protocol servers that extend AI capabilities
2. **VSCode Extensions** - Extensions from the VSCode Marketplace including:
   - Themes and Icon Themes
   - Language Support (syntax highlighting, grammars)
   - Language Servers (LSP)
   - Code Snippets
   - Debuggers
   - Formatters
   - Linters

### Key Features

- **Unified Marketplace**: Browse both MCP and VSCode extensions in one place
- **Search & Filter**: Search by name, description, or author. Filter by category or installation status
- **Compatibility Checking**: Automatic compatibility checking for VSCode extensions
- **Installation Tracking**: Track installed extensions across sessions
- **Extension Types**: Clear indicators showing whether an extension is MCP or VSCode-based

## Using Extensions

### Browsing Extensions

1. Open the Extensions panel in the left sidebar
2. Use the search bar to find specific extensions
3. Filter by category using the category buttons
4. Filter by installation status (All, Installed, Not Installed)

### Installing Extensions

1. Find the extension you want to install
2. Click the "Install" button
3. The extension will be registered in your system
4. Some extensions may require a restart to take effect

### Extension Types

#### MCP Servers
- Extend AI capabilities through the Model Context Protocol
- Require configuration in the MCP config file (`~/.ai_agent/mcp_config.json`)
- Configuration details are shown in the extension card after installation

#### VSCode Extensions
- Provide UI enhancements, language support, and developer tools
- Automatically compatible with the system (compatibility warnings shown if needed)
- No additional configuration required for most extensions

## Extension Categories

### Themes
- Color themes for the editor
- Icon themes for file explorer

### Languages
- Syntax highlighting for programming languages
- Language grammars and TextMate bundles

### Language Servers
- LSP (Language Server Protocol) implementations
- Provide features like autocomplete, error checking, refactoring

### Snippets
- Code snippets for faster development
- Expand snippets by typing the prefix and pressing Tab

### Debuggers
- Debugging support for various languages
- May require additional setup

### Formatters & Linters
- Code formatting tools
- Code linting and error detection

## Compatibility

### VSCode Extensions

Most VSCode extensions are compatible with the system. However, some limitations apply:

- **Native Extensions**: Extensions requiring native modules may not work
- **Electron-Specific**: Extensions tightly coupled to Electron may have issues
- **Version Requirements**: Extensions requiring very new VSCode versions may not be fully compatible

Compatibility warnings are shown in the extension card if an extension may have limited compatibility.

### MCP Servers

MCP servers require:
- Proper installation of dependencies (Node.js, Python, etc.)
- Configuration in the MCP config file
- Backend restart after configuration

## Technical Details

### Backend

- **VSCode Extension Service** (`backend/services/vscode_extension_service.py`):
  - Fetches extensions from VSCode Marketplace API
  - Parses extension metadata
  - Checks compatibility
  - Provides search and filtering

- **Extensions API** (`backend/api/extensions.py`):
  - Unified endpoint for both MCP and VSCode extensions
  - Handles installation and uninstallation
  - Provides extension details and configuration

### Frontend

- **Extensions UI** (`frontend/src/components/IDELayout.js`):
  - Displays extensions with type indicators
  - Shows compatibility warnings
  - Provides installation/uninstallation controls
  - Displays configuration for MCP servers

### Storage

- Installed extensions are stored in `~/.ai_agent/installed_extensions.json`
- MCP server configurations are stored in `~/.ai_agent/mcp_config.json`
- Extension cache is stored in `~/.ai_agent/extensions_cache/`

## API Endpoints

### Get Extensions
```
GET /api/extensions?category=all&search=python&source=all
```

Parameters:
- `category`: Extension category (all, themes, languages, etc.)
- `search`: Search query
- `source`: Extension source (all, mcp, vscode)

### Get Installed Extensions
```
GET /api/extensions/installed
```

### Get Extension Details
```
GET /api/extensions/{extension_id}
```

### Install Extension
```
POST /api/extensions/{extension_id}/install
```

### Uninstall Extension
```
DELETE /api/extensions/{extension_id}/install
```

## Requirements

- Python 3.8+
- `aiohttp` package (for VSCode Marketplace API access)
- Internet connection (for browsing and installing VSCode extensions)

## Installation

The VSCode extension support is included by default. To ensure all dependencies are installed:

```bash
pip install -r requirements.txt
```

The `aiohttp` package is required for fetching extensions from the VSCode Marketplace.

## Troubleshooting

### Extensions Not Loading

1. Check your internet connection (required for VSCode Marketplace)
2. Check backend logs for errors
3. Verify `aiohttp` is installed: `pip install aiohttp`

### Extension Installation Fails

1. Check extension compatibility warnings
2. Verify you have write permissions to `~/.ai_agent/`
3. Check backend logs for specific error messages

### MCP Server Not Working

1. Verify the server is configured in `~/.ai_agent/mcp_config.json`
2. Check that all dependencies are installed
3. Restart the backend server
4. Check backend logs for MCP server errors

## Future Enhancements

- VSIX file download and extraction
- Extension activation/deactivation
- Extension settings management
- Extension updates
- Local extension installation from VSIX files
- Extension recommendations based on file types

## Notes

- VSCode extensions are fetched from the public marketplace API
- Extension metadata is cached for performance
- Installation currently registers extensions; full VSIX extraction coming soon
- Some VSCode extensions may require additional runtime dependencies

