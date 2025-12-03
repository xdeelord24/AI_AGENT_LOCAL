import React, { useState, useEffect, useRef } from 'react';
import { Search, Palette, Settings, FileText, Code, Terminal, Folder } from 'lucide-react';
import { getAvailableThemes, applyTheme, applyDefaultTheme } from '../utils/themeManager';
import { ApiService } from '../services/api';
import toast from 'react-hot-toast';

const CommandPalette = ({ isOpen, onClose, onNavigate }) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [availableThemes, setAvailableThemes] = useState([]);
  const [activeThemeId, setActiveThemeId] = useState(null);
  const [showThemePicker, setShowThemePicker] = useState(false);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Load themes when palette opens
  useEffect(() => {
    if (isOpen) {
      // Always reload themes when opening to get latest installed themes
      loadThemes();
      setQuery('');
      setSelectedIndex(0);
      setShowThemePicker(false);
      // Focus input after a short delay to ensure it's rendered
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus();
        }
      }, 100);
    }
  }, [isOpen]);

  const loadThemes = async () => {
    try {
      const response = await ApiService.getAvailableThemes();
      const themes = response.themes || [];
      console.log('Loaded themes:', themes.length, themes);
      setAvailableThemes(themes);
      
      const activeTheme = await ApiService.getActiveTheme();
      if (activeTheme && activeTheme.theme_id) {
        setActiveThemeId(activeTheme.theme_id);
      } else {
        const savedTheme = localStorage.getItem('activeTheme');
        if (savedTheme) {
          setActiveThemeId(savedTheme);
        }
      }
    } catch (error) {
      console.error('Error loading themes:', error);
      // Set empty array on error so UI shows appropriate message
      setAvailableThemes([]);
    }
  };

  // Commands list
  const allCommands = [
    {
      id: 'theme',
      label: 'Preferences: Color Theme',
      icon: Palette,
      category: 'Preferences',
      description: 'Change the color theme',
      action: () => {
        setShowThemePicker(true);
        setQuery('');
        setSelectedIndex(0);
      }
    },
    {
      id: 'settings',
      label: 'Preferences: Open Settings',
      icon: Settings,
      category: 'Preferences',
      description: 'Open Settings page',
      action: () => {
        if (onNavigate) onNavigate('settings');
        onClose();
      }
    },
    {
      id: 'new-file',
      label: 'File: New File',
      icon: FileText,
      category: 'File',
      description: 'Create a new file',
      action: () => {
        // Trigger new file creation
        onClose();
      }
    },
    {
      id: 'open-file',
      label: 'File: Open File',
      icon: Folder,
      category: 'File',
      description: 'Open a file',
      action: () => {
        // Trigger file open dialog
        onClose();
      }
    },
    {
      id: 'terminal',
      label: 'View: Toggle Terminal',
      icon: Terminal,
      category: 'View',
      description: 'Show or hide the terminal',
      action: () => {
        // Toggle terminal
        onClose();
      }
    },
  ];

  // Filter commands based on query
  const filteredCommands = showThemePicker
    ? [
        // Default theme option
        {
          id: 'theme-default',
          label: 'Default (VS Dark)',
          icon: Palette,
          category: 'Theme',
          isTheme: true,
          themeId: 'default',
          isActive: !activeThemeId || activeThemeId === 'vs-dark' || activeThemeId === 'default',
          action: async () => {
            const success = await applyDefaultTheme();
            if (success) {
              setActiveThemeId('default');
              toast.success('Default theme applied');
              // Dispatch custom event for theme change
              window.dispatchEvent(new Event('themeChanged'));
              onClose();
            } else {
              toast.error('Failed to apply default theme');
            }
          }
        },
        // Available themes
        ...availableThemes
          .filter(theme => {
            if (!query) return true;
            const q = query.toLowerCase();
            const themeName = (theme.label || theme.extension_name || theme.id || '').toLowerCase();
            return themeName.includes(q);
          })
          .map((theme, index) => ({
            id: `theme-${theme.id}`,
            label: theme.label || theme.extension_name || theme.id,
            icon: Palette,
            category: 'Theme',
            isTheme: true,
            themeId: theme.id,
            isActive: theme.id === activeThemeId,
            action: async () => {
              // Pass extension_id if available to help with automatic theme extraction
              const success = await applyTheme(theme.id, theme.extension_id);
              if (success) {
                setActiveThemeId(theme.id);
                toast.success('Theme applied successfully');
                // Dispatch custom event for theme change
                window.dispatchEvent(new Event('themeChanged'));
                onClose();
              } else {
                toast.error('Failed to apply theme. Make sure themes are extracted from the extension.');
              }
            }
          }))
      ]
    : allCommands.filter(cmd => {
        if (!query) return true;
        const q = query.toLowerCase();
        return cmd.label.toLowerCase().includes(q) || 
               cmd.category.toLowerCase().includes(q) ||
               (cmd.description && cmd.description.toLowerCase().includes(q));
      });

  // Handle keyboard navigation
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (showThemePicker) {
          setShowThemePicker(false);
          setQuery('');
        } else {
          onClose();
        }
        e.preventDefault();
        return;
      }

      if (e.key === 'ArrowDown') {
        setSelectedIndex(prev => Math.min(prev + 1, filteredCommands.length - 1));
        e.preventDefault();
        return;
      }

      if (e.key === 'ArrowUp') {
        setSelectedIndex(prev => Math.max(prev - 1, 0));
        e.preventDefault();
        return;
      }

      if (e.key === 'Enter') {
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].action();
        }
        e.preventDefault();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, selectedIndex, filteredCommands, showThemePicker, onClose]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && filteredCommands[selectedIndex]) {
      const selectedElement = listRef.current.children[selectedIndex];
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [selectedIndex, filteredCommands]);

  if (!isOpen) return null;

  const handleThemeSelect = async (themeId) => {
    const success = await applyTheme(themeId);
    if (success) {
      setActiveThemeId(themeId);
      toast.success('Theme applied successfully');
      onClose();
    } else {
      toast.error('Failed to apply theme');
    }
  };

  return (
    <div 
      className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-start justify-center pt-32"
      onClick={onClose}
    >
      <div 
        className="bg-dark-800 border border-dark-700 rounded-lg shadow-2xl w-full max-w-2xl mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center px-4 py-3 border-b border-dark-700">
          <Search className="w-5 h-5 text-dark-400 mr-3" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder={showThemePicker ? "Select theme..." : "Type command name..."}
            className="flex-1 bg-transparent text-dark-100 placeholder-dark-400 focus:outline-none text-sm"
            autoFocus
          />
          {showThemePicker && (
            <button
              onClick={() => {
                setShowThemePicker(false);
                setQuery('');
              }}
              className="ml-2 px-2 py-1 text-xs text-dark-400 hover:text-dark-200"
            >
              ← Back
            </button>
          )}
        </div>

        {/* Commands list */}
        <div 
          ref={listRef}
          className="max-h-96 overflow-y-auto"
        >
          {filteredCommands.length === 0 ? (
            <div className="px-4 py-8 text-center text-dark-400 text-sm">
              {showThemePicker 
                ? "No themes available. Install theme extensions from the Extensions panel."
                : "No commands found"}
            </div>
          ) : (
            filteredCommands.map((command, index) => {
              const Icon = command.icon || FileText;
              const isSelected = index === selectedIndex;
              const isActiveTheme = command.isTheme && command.themeId === activeThemeId;

              return (
                <div
                  key={command.id}
                  onClick={() => command.action()}
                  className={`px-4 py-3 flex items-center cursor-pointer transition-colors ${
                    isSelected 
                      ? 'bg-dark-700' 
                      : 'hover:bg-dark-700'
                  }`}
                >
                  <div className="flex items-center flex-1 min-w-0">
                    <Icon className={`w-5 h-5 mr-3 flex-shrink-0 ${
                      isActiveTheme ? 'text-primary-400' : 'text-dark-400'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm ${
                        isActiveTheme ? 'text-primary-400 font-medium' : 'text-dark-100'
                      }`}>
                        {command.label}
                      </div>
                      {command.category && !showThemePicker && (
                        <div className="text-xs text-dark-400 mt-0.5">
                          {command.category}
                        </div>
                      )}
                      {command.description && !showThemePicker && (
                        <div className="text-xs text-dark-500 mt-0.5">
                          {command.description}
                        </div>
                      )}
                      {command.isTheme && (
                        <div className={`text-xs mt-0.5 ${
                          isActiveTheme ? 'text-primary-400' : 'text-dark-500'
                        }`}>
                          {isActiveTheme ? '● Active' : 'Click to apply'}
                        </div>
                      )}
                    </div>
                  </div>
                  {isSelected && (
                    <div className="ml-2 text-xs text-dark-400">
                      ↵
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-dark-700 flex items-center justify-between text-xs text-dark-400">
          <div className="flex items-center space-x-4">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>Esc {showThemePicker ? 'Back' : 'Close'}</span>
          </div>
          {showThemePicker ? (
            <span>{filteredCommands.length} theme{filteredCommands.length !== 1 ? 's' : ''} available</span>
          ) : (
            <span>{filteredCommands.length} command{filteredCommands.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;

