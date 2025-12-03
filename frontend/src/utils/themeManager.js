/**
 * Theme Manager Utility
 * Handles loading and applying VSCode theme extensions
 */

import { ApiService } from '../services/api';

// Store Monaco instance reference for theme registration
let monacoInstance = null;

/**
 * Set Monaco instance for theme registration
 */
export function setMonacoInstance(monaco) {
  monacoInstance = monaco;
}

/**
 * Get Monaco instance
 */
export function getMonacoInstance() {
  return monacoInstance;
}

/**
 * Convert VSCode theme colors to CSS custom properties
 * Maps VSCode color tokens to Tailwind-compatible CSS variables
 */
function convertThemeColorsToCSS(themeColors) {
  const cssVars = {};
  
  // Comprehensive mapping of VSCode colors to CSS variables
  // These will override Tailwind's default dark theme colors
  const colorMap = {
    // Editor colors
    'editor.background': '--color-dark-900',
    'editor.foreground': '--color-dark-50',
    'editorLineNumber.foreground': '--color-dark-400',
    'editorLineNumber.activeForeground': '--color-dark-200',
    
    // Sidebar colors
    'sideBar.background': '--color-dark-800',
    'sideBar.foreground': '--color-dark-100',
    'sideBarTitle.foreground': '--color-dark-200',
    'sideBarSectionHeader.background': '--color-dark-700',
    
    // Activity bar
    'activityBar.background': '--color-dark-900',
    'activityBar.foreground': '--color-dark-300',
    'activityBar.activeBorder': '--color-primary-500',
    
    // Status bar
    'statusBar.background': '--color-dark-800',
    'statusBar.foreground': '--color-dark-200',
    
    // Panel
    'panel.background': '--color-dark-900',
    'panel.border': '--color-dark-700',
    
    // Input fields
    'input.background': '--color-dark-700',
    'input.foreground': '--color-dark-100',
    'input.border': '--color-dark-600',
    
    // Buttons
    'button.background': '--color-primary-600',
    'button.foreground': '--color-white',
    'button.hoverBackground': '--color-primary-700',
    
    // Lists
    'list.activeSelectionBackground': '--color-dark-700',
    'list.inactiveSelectionBackground': '--color-dark-800',
    'list.hoverBackground': '--color-dark-700',
    
    // Scrollbar
    'scrollbar.shadow': '--color-dark-700',
    'scrollbarSlider.background': '--color-dark-600',
    'scrollbarSlider.hoverBackground': '--color-dark-500',
    
    // Borders and dividers
    'border': '--color-dark-700',
    'divider': '--color-dark-700',
  };
  
  // Apply mapped colors
  for (const [vscodeKey, cssVar] of Object.entries(colorMap)) {
    if (themeColors[vscodeKey]) {
      cssVars[cssVar] = themeColors[vscodeKey];
    }
  }
  
  return cssVars;
}

/**
 * Convert VSCode theme colors to Monaco editor theme format
 */
function convertToMonacoTheme(themeColors, tokenColors = []) {
  const monacoTheme = {
    base: 'vs-dark', // Base theme
    inherit: true,
    rules: [],
    colors: {}
  };
  
  // Map VSCode color keys to Monaco color keys
  const colorMapping = {
    'editor.background': 'editor.background',
    'editor.foreground': 'editor.foreground',
    'editorLineNumber.foreground': 'editorLineNumber.foreground',
    'editorLineNumber.activeForeground': 'editorLineNumber.activeForeground',
    'editor.selectionBackground': 'editor.selectionBackground',
    'editor.selectionHighlightBackground': 'editor.selectionHighlightBackground',
    'editor.inactiveSelectionBackground': 'editor.inactiveSelectionBackground',
    'editorCursor.foreground': 'editorCursor.foreground',
    'editorWhitespace.foreground': 'editorWhitespace.foreground',
    'editorIndentGuide.background': 'editorIndentGuide.background',
    'editorIndentGuide.activeBackground': 'editorIndentGuide.activeBackground',
    'editor.lineHighlightBackground': 'editor.lineHighlightBackground',
    'editor.findMatchBackground': 'editor.findMatchBackground',
    'editor.findMatchHighlightBackground': 'editor.findMatchHighlightBackground',
    'editorBracketMatch.background': 'editorBracketMatch.background',
    'editorBracketMatch.border': 'editorBracketMatch.border',
    'editorWidget.background': 'editorWidget.background',
    'editorWidget.border': 'editorWidget.border',
    'editorSuggestWidget.background': 'editorSuggestWidget.background',
    'editorSuggestWidget.border': 'editorSuggestWidget.border',
    'editorSuggestWidget.foreground': 'editorSuggestWidget.foreground',
    'editorSuggestWidget.selectedBackground': 'editorSuggestWidget.selectedBackground',
    'scrollbarSlider.background': 'scrollbarSlider.background',
    'scrollbarSlider.hoverBackground': 'scrollbarSlider.hoverBackground',
    'scrollbarSlider.activeBackground': 'scrollbarSlider.activeBackground',
  };
  
  // Convert colors
  for (const [vscodeKey, monacoKey] of Object.entries(colorMapping)) {
    if (themeColors[vscodeKey]) {
      monacoTheme.colors[monacoKey] = themeColors[vscodeKey];
    }
  }
  
  // Convert token colors (syntax highlighting)
  if (Array.isArray(tokenColors)) {
    for (const tokenRule of tokenColors) {
      if (tokenRule.settings && tokenRule.scope) {
        const scopes = Array.isArray(tokenRule.scope) ? tokenRule.scope : [tokenRule.scope];
        for (const scope of scopes) {
          if (tokenRule.settings.foreground) {
            monacoTheme.rules.push({
              token: scope,
              foreground: tokenRule.settings.foreground,
              background: tokenRule.settings.background,
              fontStyle: tokenRule.settings.fontStyle
            });
          }
        }
      }
    }
  }
  
  return monacoTheme;
}

/**
 * Register Monaco editor theme
 */
function registerMonacoTheme(themeId, themeColors, tokenColors = []) {
  if (!monacoInstance) {
    console.warn('Monaco instance not available, cannot register theme');
    return false;
  }
  
  try {
    const monacoTheme = convertToMonacoTheme(themeColors, tokenColors);
    monacoInstance.editor.defineTheme(themeId, monacoTheme);
    console.log(`Registered Monaco theme: ${themeId}`);
    return true;
  } catch (error) {
    console.error(`Error registering Monaco theme:`, error);
    return false;
  }
}

/**
 * Apply theme to Monaco editor (register and set)
 * This function ensures the theme is registered before applying it
 */
export async function applyMonacoTheme(themeId) {
  if (!monacoInstance) {
    console.warn('Monaco instance not available');
    return false;
  }
  
  // If it's the default theme, just set it
  if (themeId === 'vs-dark' || themeId === 'default' || !themeId) {
    try {
      monacoInstance.editor.setTheme('vs-dark');
      return true;
    } catch (error) {
      console.error('Failed to set default Monaco theme:', error);
      return false;
    }
  }
  
  // For custom themes, we need to load and register them
  try {
    const themeResponse = await ApiService.getThemeData(themeId);
    const theme = themeResponse?.theme;
    
    if (!theme || !theme.colors) {
      console.warn(`Theme ${themeId} not found or has no colors`);
      monacoInstance.editor.setTheme('vs-dark');
      return false;
    }
    
    // Register the theme first
    const registered = registerMonacoTheme(themeId, theme.colors, theme.tokenColors || []);
    if (registered) {
      // Set the theme immediately after registration
      // Use a small delay to ensure registration is complete
      try {
        monacoInstance.editor.setTheme(themeId);
        console.log(`Applied Monaco theme: ${themeId}`);
        return true;
      } catch (setError) {
        console.error(`Failed to set theme ${themeId} after registration:`, setError);
        // Try again after a brief moment
        setTimeout(() => {
          try {
            monacoInstance.editor.setTheme(themeId);
            console.log(`Applied Monaco theme ${themeId} (retry)`);
          } catch (retryError) {
            console.error('Retry failed:', retryError);
            monacoInstance.editor.setTheme('vs-dark');
          }
        }, 100);
        return true; // Return true since registration succeeded
      }
    } else {
      console.warn('Theme registration failed, using vs-dark');
      monacoInstance.editor.setTheme('vs-dark');
      return false;
    }
  } catch (error) {
    console.error(`Error applying Monaco theme ${themeId}:`, error);
    try {
      monacoInstance.editor.setTheme('vs-dark');
    } catch (fallbackError) {
      console.error('Failed to set fallback theme:', fallbackError);
    }
    return false;
  }
}

/**
 * Apply theme CSS variables to the document root
 * This will override Tailwind's default colors
 */
export function applyThemeCSS(themeColors) {
  const root = document.documentElement;
  const cssVars = convertThemeColorsToCSS(themeColors);
  
  // Apply CSS variables
  for (const [varName, value] of Object.entries(cssVars)) {
    root.style.setProperty(varName, value);
  }
  
  // Also create a style element with theme-specific overrides
  let themeStyle = document.getElementById('vscode-theme-overrides');
  if (!themeStyle) {
    themeStyle = document.createElement('style');
    themeStyle.id = 'vscode-theme-overrides';
    document.head.appendChild(themeStyle);
  }
  
  // Generate CSS rules that use these variables
  const cssVarEntries = Object.entries(cssVars)
    .map(([varName, val]) => `${varName}: ${val};`)
    .join('\n      ');
  
  const cssRules = `
    :root {
      ${cssVarEntries}
    }
    
    /* Override Tailwind dark colors with theme colors */
    .bg-dark-900 { background-color: var(--color-dark-900, #0f172a) !important; }
    .bg-dark-800 { background-color: var(--color-dark-800, #1e293b) !important; }
    .bg-dark-700 { background-color: var(--color-dark-700, #334155) !important; }
    .bg-dark-600 { background-color: var(--color-dark-600, #475569) !important; }
    
    .text-dark-50 { color: var(--color-dark-50, #f8fafc) !important; }
    .text-dark-100 { color: var(--color-dark-100, #f1f5f9) !important; }
    .text-dark-200 { color: var(--color-dark-200, #e2e8f0) !important; }
    .text-dark-300 { color: var(--color-dark-300, #cbd5e1) !important; }
    .text-dark-400 { color: var(--color-dark-400, #94a3b8) !important; }
    
    .border-dark-700 { border-color: var(--color-dark-700, #334155) !important; }
    .border-dark-600 { border-color: var(--color-dark-600, #475569) !important; }
  `;
  
  themeStyle.textContent = cssRules;
}

/**
 * Load and apply a theme
 * @param {string} themeId - The theme ID (format: extension_id_theme_id)
 * @param {string} extensionId - Optional extension ID to use for extraction if theme not found
 */
export async function applyTheme(themeId, extensionId = null) {
  try {
    // Get theme data
    let themeResponse;
    try {
      themeResponse = await ApiService.getThemeData(themeId);
    } catch (error) {
      // If theme not found (404), try to extract themes from the extension
      if (error.response?.status === 404) {
        let extId = extensionId;
        
        // If extensionId not provided, try to extract it from themeId
        if (!extId && themeId.includes('_')) {
          // Extract extension_id from theme_id (format: extension_id_theme_id)
          // Find the last underscore to separate extension_id from theme_id
          const lastUnderscoreIndex = themeId.lastIndexOf('_');
          if (lastUnderscoreIndex > 0) {
            extId = themeId.substring(0, lastUnderscoreIndex);
          }
        }
        
        if (extId) {
          console.log(`Theme file not found, attempting to extract themes from extension: ${extId}`);
          
          try {
            // Extract themes from the extension
            await ApiService.extractThemesFromExtension(extId);
            // Retry getting theme data
            themeResponse = await ApiService.getThemeData(themeId);
          } catch (extractError) {
            console.error(`Failed to extract themes:`, extractError);
            throw error; // Re-throw original error
          }
        } else {
          throw error;
        }
      } else {
        throw error;
      }
    }
    
    const theme = themeResponse?.theme;
    
    if (!theme) {
      console.warn(`Theme ${themeId} not found`);
      return false;
    }
    
    if (!theme.colors || Object.keys(theme.colors).length === 0) {
      console.warn(`Theme ${themeId} has no color data`);
      return false;
    }
    
    // Apply theme colors to CSS
    applyThemeCSS(theme.colors);
    
    // Register and apply Monaco editor theme
    const registered = registerMonacoTheme(themeId, theme.colors, theme.tokenColors || []);
    
    // Set Monaco editor theme if instance is available
    if (monacoInstance && registered) {
      try {
        // Apply theme immediately after registration
        monacoInstance.editor.setTheme(themeId);
        console.log(`Applied Monaco theme: ${themeId}`);
      } catch (error) {
        console.warn(`Failed to set Monaco theme, falling back to vs-dark:`, error);
        // Fallback to vs-dark if custom theme fails
        try {
          monacoInstance.editor.setTheme('vs-dark');
        } catch (fallbackError) {
          console.error('Failed to set fallback theme:', fallbackError);
        }
      }
    } else if (monacoInstance && !registered) {
      console.warn('Theme registration failed, using vs-dark');
      try {
        monacoInstance.editor.setTheme('vs-dark');
      } catch (error) {
        console.error('Failed to set fallback theme:', error);
      }
    }
    
    // Store active theme
    await ApiService.applyTheme(themeId);
    
    // Store in localStorage for persistence
    localStorage.setItem('activeTheme', themeId);
    
    // Dispatch custom event for theme change
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('themeChanged'));
    }
    
    return true;
  } catch (error) {
    console.error(`Error applying theme ${themeId}:`, error);
    return false;
  }
}

/**
 * Load active theme on app startup
 */
export async function loadActiveTheme() {
  try {
    // Check localStorage first
    const savedTheme = localStorage.getItem('activeTheme');
    if (savedTheme) {
      const applied = await applyTheme(savedTheme);
      if (applied) {
        return savedTheme;
      }
    }
    
    // Check backend for active theme
    const activeTheme = await ApiService.getActiveTheme();
    if (activeTheme && activeTheme.theme_id) {
      const applied = await applyTheme(activeTheme.theme_id);
      if (applied) {
        return activeTheme.theme_id;
      }
    }
    
    return null;
  } catch (error) {
    console.error('Error loading active theme:', error);
    return null;
  }
}

/**
 * Get available themes
 */
export async function getAvailableThemes() {
  try {
    const response = await ApiService.getAvailableThemes();
    return response.themes || [];
  } catch (error) {
    console.error('Error getting available themes:', error);
    return [];
  }
}

/**
 * Apply default theme (reset to vs-dark)
 */
export async function applyDefaultTheme() {
  try {
    // Reset CSS variables to defaults
    const root = document.documentElement;
    const defaultColors = {
      '--color-dark-900': '#0f172a',
      '--color-dark-800': '#1e293b',
      '--color-dark-700': '#334155',
      '--color-dark-600': '#475569',
      '--color-dark-50': '#f8fafc',
      '--color-dark-100': '#f1f5f9',
      '--color-dark-200': '#e2e8f0',
      '--color-dark-300': '#cbd5e1',
      '--color-dark-400': '#94a3b8',
    };
    
    for (const [varName, value] of Object.entries(defaultColors)) {
      root.style.setProperty(varName, value);
    }
    
    // Reset Monaco editor to default theme
    if (monacoInstance) {
      monacoInstance.editor.setTheme('vs-dark');
    }
    
    // Clear active theme
    await ApiService.applyTheme('default');
    localStorage.removeItem('activeTheme');
    
    // Dispatch custom event for theme change
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('themeChanged'));
    }
    
    return true;
  } catch (error) {
    console.error('Error applying default theme:', error);
    return false;
  }
}

