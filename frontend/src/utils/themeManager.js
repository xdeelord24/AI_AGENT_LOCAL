/**
 * Theme Manager Utility
 * Handles loading and applying VSCode theme extensions
 */

import { ApiService } from '../services/api';

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
 */
export async function applyTheme(themeId) {
  try {
    // Get theme data
    const themeResponse = await ApiService.getThemeData(themeId);
    const theme = themeResponse.theme;
    
    if (!theme || !theme.colors) {
      console.warn(`Theme ${themeId} has no color data`);
      return false;
    }
    
    // Apply theme colors
    applyThemeCSS(theme.colors);
    
    // Store active theme
    await ApiService.applyTheme(themeId);
    
    // Store in localStorage for persistence
    localStorage.setItem('activeTheme', themeId);
    
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

