import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { 
  MessageSquare, 
  FolderOpen, 
  Code, 
  Settings, 
  Bot, 
  Wifi, 
  WifiOff,
  ChevronDown,
  ChevronRight
} from 'lucide-react';

const Layout = ({ 
  children, 
  isConnected, 
  currentModel, 
  availableModels, 
  onModelSelect 
}) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const location = useLocation();

  const navigation = [
    { name: 'Chat', href: '/chat', icon: MessageSquare },
    { name: 'Files', href: '/files', icon: FolderOpen },
    { name: 'Editor', href: '/editor', icon: Code },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  const isActive = (path) => location.pathname === path;

  return (
    <div className="flex h-screen bg-dark-900">
      {/* Sidebar */}
      <div className={`${sidebarCollapsed ? 'w-16' : 'w-64'} transition-all duration-300 bg-dark-800 border-r border-dark-700 flex flex-col`}>
        {/* Header */}
        <div className="p-4 border-b border-dark-700">
          <div className="flex items-center justify-between">
            {!sidebarCollapsed && (
              <div className="flex items-center space-x-2">
                <Bot className="w-8 h-8 text-primary-500" />
                <span className="text-lg font-bold text-dark-50">AI Agent</span>
              </div>
            )}
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="p-1 rounded hover:bg-dark-700 transition-colors"
            >
              {sidebarCollapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Connection Status */}
        <div className="p-4 border-b border-dark-700">
          <div className="flex items-center space-x-2">
            {isConnected ? (
              <Wifi className="w-4 h-4 text-green-500" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-500" />
            )}
            {!sidebarCollapsed && (
              <span className={`text-sm ${isConnected ? 'text-green-500' : 'text-red-500'}`}>
                {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            )}
          </div>
        </div>

        {/* Model Selection */}
        {!sidebarCollapsed && (
          <div className="p-4 border-b border-dark-700">
            <div className="relative">
              <label className="block text-xs font-medium text-dark-400 mb-2">
                AI Model
              </label>
              <button
                onClick={() => setShowModelDropdown(!showModelDropdown)}
                className="w-full flex items-center justify-between p-2 bg-dark-700 border border-dark-600 rounded text-sm hover:bg-dark-600 transition-colors"
              >
                <span className="truncate">{currentModel}</span>
                <ChevronDown className="w-4 h-4" />
              </button>
              
              {showModelDropdown && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-dark-700 border border-dark-600 rounded shadow-lg z-50">
                  {availableModels.map((model) => (
                    <button
                      key={model}
                      onClick={() => {
                        onModelSelect(model);
                        setShowModelDropdown(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-dark-600 transition-colors ${
                        model === currentModel ? 'text-primary-500' : 'text-dark-300'
                      }`}
                    >
                      {model}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Navigation */}
        <nav className="flex-1 p-4">
          <ul className="space-y-2">
            {navigation.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.name}>
                  <Link
                    to={item.href}
                    className={`flex items-center space-x-3 px-3 py-2 rounded-lg transition-colors ${
                      isActive(item.href)
                        ? 'bg-primary-600 text-white'
                        : 'text-dark-300 hover:bg-dark-700 hover:text-dark-100'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    {!sidebarCollapsed && <span>{item.name}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer */}
        {!sidebarCollapsed && (
          <div className="p-4 border-t border-dark-700">
            <div className="text-xs text-dark-400">
              <div>Offline AI Agent</div>
              <div>Version 1.0.0</div>
            </div>
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {children}
      </div>
    </div>
  );
};

export default Layout;
