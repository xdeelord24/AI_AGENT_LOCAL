import React, { useState, useEffect } from 'react';
import { 
  Settings as SettingsIcon, 
  Bot, 
  Database, 
  Monitor, 
  Wifi, 
  WifiOff,
  RefreshCw,
  Check,
  X
} from 'lucide-react';
import { ApiService } from '../services/api';
import toast from 'react-hot-toast';

const Settings = () => {
  const [settings, setSettings] = useState({
    currentModel: 'codellama',
    availableModels: [],
    ollamaUrl: 'http://localhost:5000',
    ollamaDirectUrl: 'http://localhost:11434',
    useProxy: true,
    autoSave: true,
    theme: 'dark',
    fontSize: 14,
    tabSize: 2,
    wordWrap: true,
    minimap: true,
    lineNumbers: true,
  });
  
  const [isSaving, setIsSaving] = useState(false);
  
  const [connectionStatus, setConnectionStatus] = useState({
    ollama: false,
    backend: false,
  });
  
  const [isLoading, setIsLoading] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);

  useEffect(() => {
    loadSettings();
    checkConnections();
  }, []);

  const loadSettings = async () => {
    try {
      const [modelsResponse, statusResponse, backendSettings] = await Promise.all([
        ApiService.getModels(),
        ApiService.getChatStatus(),
        ApiService.getSettings().catch(() => null)
      ]);
      
      setSettings(prev => ({
        ...prev,
        availableModels: modelsResponse.models || [],
        currentModel: statusResponse.current_model || 'codellama',
        ...(backendSettings && {
          ollamaUrl: backendSettings.ollama_url || prev.ollamaUrl,
          ollamaDirectUrl: backendSettings.ollama_direct_url || prev.ollamaDirectUrl,
          useProxy: backendSettings.use_proxy !== undefined ? backendSettings.use_proxy : prev.useProxy
        })
      }));
    } catch (error) {
      console.error('Error loading settings:', error);
    }
  };

  const checkConnections = async () => {
    setIsLoading(true);
    try {
      // Check backend connection
      const backendResponse = await ApiService.get('/health');
      setConnectionStatus(prev => ({
        ...prev,
        backend: backendResponse.status === 'healthy'
      }));

      // Check Ollama connection
      const ollamaResponse = await ApiService.getChatStatus();
      setConnectionStatus(prev => ({
        ...prev,
        ollama: ollamaResponse.ollama_connected
      }));
    } catch (error) {
      console.error('Error checking connections:', error);
      setConnectionStatus({
        backend: false,
        ollama: false
      });
    } finally {
      setIsLoading(false);
    }
  };

  const testOllamaConnection = async () => {
    setIsTestingConnection(true);
    try {
      const response = await ApiService.testOllamaConnection();
      if (response.connected) {
        toast.success('Ollama connection successful!');
        setConnectionStatus(prev => ({ ...prev, ollama: true }));
        // Reload models if connection successful
        if (response.available_models) {
          setSettings(prev => ({
            ...prev,
            availableModels: response.available_models
          }));
        }
      } else {
        toast.error(response.message || 'Ollama is not running or not accessible');
        setConnectionStatus(prev => ({ ...prev, ollama: false }));
      }
    } catch (error) {
      console.error('Error testing Ollama connection:', error);
      toast.error('Failed to connect to Ollama');
      setConnectionStatus(prev => ({ ...prev, ollama: false }));
    } finally {
      setIsTestingConnection(false);
    }
  };
  
  const saveOllamaSettings = async () => {
    setIsSaving(true);
    try {
      await ApiService.updateSettings({
        ollama_url: settings.ollamaUrl,
        ollama_direct_url: settings.ollamaDirectUrl,
        use_proxy: settings.useProxy
      });
      toast.success('Ollama settings saved successfully!');
      // Test connection after saving
      await testOllamaConnection();
    } catch (error) {
      console.error('Error saving Ollama settings:', error);
      toast.error(error.response?.data?.detail || 'Failed to save Ollama settings');
    } finally {
      setIsSaving(false);
    }
  };

  const selectModel = async (modelName) => {
    try {
      await ApiService.selectModel(modelName);
      setSettings(prev => ({ ...prev, currentModel: modelName }));
      toast.success(`Model changed to ${modelName}`);
    } catch (error) {
      console.error('Error selecting model:', error);
      toast.error('Failed to change model');
    }
  };

  const handleSettingChange = (key, value) => {
    setSettings(prev => ({ ...prev, [key]: value }));
    // Save to localStorage
    localStorage.setItem('offline-ai-settings', JSON.stringify({
      ...settings,
      [key]: value
    }));
  };

  const resetSettings = async () => {
    const defaultSettings = {
      currentModel: 'codellama',
      availableModels: [],
      ollamaUrl: 'http://localhost:5000',
      ollamaDirectUrl: 'http://localhost:11434',
      useProxy: true,
      autoSave: true,
      theme: 'dark',
      fontSize: 14,
      tabSize: 2,
      wordWrap: true,
      minimap: true,
      lineNumbers: true,
    };
    setSettings(defaultSettings);
    localStorage.setItem('offline-ai-settings', JSON.stringify(defaultSettings));
    
    // Also reset backend settings
    try {
      await ApiService.updateSettings({
        ollama_url: defaultSettings.ollamaUrl,
        ollama_direct_url: defaultSettings.ollamaDirectUrl,
        use_proxy: defaultSettings.useProxy
      });
      toast.success('Settings reset to defaults');
    } catch (error) {
      console.error('Error resetting backend settings:', error);
      toast.success('Local settings reset to defaults');
    }
  };

  const getStatusIcon = (status) => {
    return status ? (
      <Check className="w-5 h-5 text-green-500" />
    ) : (
      <X className="w-5 h-5 text-red-500" />
    );
  };

  const getStatusText = (status) => {
    return status ? 'Connected' : 'Disconnected';
  };

  const getStatusColor = (status) => {
    return status ? 'text-green-500' : 'text-red-500';
  };

  return (
    <div className="flex h-full bg-dark-900">
      {/* Settings Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-8">
          {/* Header */}
          <div className="flex items-center space-x-3 mb-8">
            <SettingsIcon className="w-8 h-8 text-primary-500" />
            <h1 className="text-3xl font-bold text-dark-50">Settings</h1>
          </div>

          {/* Connection Status */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Wifi className="w-5 h-5" />
              <span>Connection Status</span>
            </h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center justify-between p-4 bg-dark-700 rounded-lg">
                <div className="flex items-center space-x-3">
                  <Bot className="w-6 h-6 text-primary-500" />
                  <div>
                    <div className="font-medium text-dark-100">Backend Service</div>
                    <div className={`text-sm ${getStatusColor(connectionStatus.backend)}`}>
                      {getStatusText(connectionStatus.backend)}
                    </div>
                  </div>
                </div>
                {getStatusIcon(connectionStatus.backend)}
              </div>

              <div className="flex items-center justify-between p-4 bg-dark-700 rounded-lg">
                <div className="flex items-center space-x-3">
                  <Database className="w-6 h-6 text-blue-500" />
                  <div>
                    <div className="font-medium text-dark-100">Ollama</div>
                    <div className={`text-sm ${getStatusColor(connectionStatus.ollama)}`}>
                      {getStatusText(connectionStatus.ollama)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {getStatusIcon(connectionStatus.ollama)}
                  <button
                    onClick={testOllamaConnection}
                    disabled={isTestingConnection}
                    className="p-1 hover:bg-dark-600 rounded transition-colors disabled:opacity-50"
                  >
                    {isTestingConnection ? (
                      <RefreshCw className="w-4 h-4 animate-spin text-primary-500" />
                    ) : (
                      <RefreshCw className="w-4 h-4 text-dark-400" />
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-4">
              <button
                onClick={checkConnections}
                disabled={isLoading}
                className="flex items-center space-x-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded transition-colors disabled:opacity-50"
              >
                {isLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                <span>Refresh Status</span>
              </button>
            </div>
          </div>

          {/* Ollama Configuration */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Database className="w-5 h-5" />
              <span>Ollama Configuration</span>
            </h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Ollama URL (Proxy)
                </label>
                <input
                  type="text"
                  value={settings.ollamaUrl}
                  onChange={(e) => handleSettingChange('ollamaUrl', e.target.value)}
                  placeholder="http://localhost:5000"
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
                <p className="text-xs text-dark-400 mt-1">URL for Ollama proxy server (if using proxy)</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Ollama Direct URL
                </label>
                <input
                  type="text"
                  value={settings.ollamaDirectUrl}
                  onChange={(e) => handleSettingChange('ollamaDirectUrl', e.target.value)}
                  placeholder="http://localhost:11434"
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
                <p className="text-xs text-dark-400 mt-1">Direct URL to Ollama server (default: http://localhost:11434)</p>
              </div>

              <div>
                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.useProxy}
                    onChange={(e) => handleSettingChange('useProxy', e.target.checked)}
                    className="w-4 h-4 text-primary-600 bg-dark-700 border-dark-600 rounded focus:ring-primary-500"
                  />
                  <span className="text-dark-300">Use Proxy Server</span>
                </label>
                <p className="text-xs text-dark-400 mt-1 ml-7">If enabled, uses the proxy URL. Otherwise, uses the direct URL.</p>
              </div>

              <div className="flex space-x-3">
                <button
                  onClick={saveOllamaSettings}
                  disabled={isSaving}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded transition-colors disabled:opacity-50 flex items-center space-x-2"
                >
                  {isSaving ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Saving...</span>
                    </>
                  ) : (
                    <span>Save Ollama Settings</span>
                  )}
                </button>
                <button
                  onClick={testOllamaConnection}
                  disabled={isTestingConnection}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors disabled:opacity-50 flex items-center space-x-2"
                >
                  {isTestingConnection ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Testing...</span>
                    </>
                  ) : (
                    <>
                      <Wifi className="w-4 h-4" />
                      <span>Test Connection</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* AI Model Settings */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Bot className="w-5 h-5" />
              <span>AI Model</span>
            </h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Current Model
                </label>
                <div className="flex items-center space-x-3">
                  <select
                    value={settings.currentModel}
                    onChange={(e) => selectModel(e.target.value)}
                    className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    {settings.availableModels.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Available Models ({settings.availableModels.length})
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {settings.availableModels.map((model) => (
                    <div
                      key={model}
                      className={`p-3 rounded-lg border ${
                        model === settings.currentModel
                          ? 'bg-primary-600 border-primary-500 text-white'
                          : 'bg-dark-700 border-dark-600 text-dark-300'
                      }`}
                    >
                      <div className="font-medium">{model}</div>
                      {model === settings.currentModel && (
                        <div className="text-xs opacity-75">Currently selected</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Editor Settings */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Monitor className="w-5 h-5" />
              <span>Editor Settings</span>
            </h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Font Size
                </label>
                <input
                  type="range"
                  min="10"
                  max="24"
                  value={settings.fontSize}
                  onChange={(e) => handleSettingChange('fontSize', parseInt(e.target.value))}
                  className="w-full"
                />
                <div className="text-sm text-dark-400 mt-1">{settings.fontSize}px</div>
              </div>

              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Tab Size
                </label>
                <input
                  type="range"
                  min="2"
                  max="8"
                  value={settings.tabSize}
                  onChange={(e) => handleSettingChange('tabSize', parseInt(e.target.value))}
                  className="w-full"
                />
                <div className="text-sm text-dark-400 mt-1">{settings.tabSize} spaces</div>
              </div>

              <div className="space-y-3">
                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.wordWrap}
                    onChange={(e) => handleSettingChange('wordWrap', e.target.checked)}
                    className="w-4 h-4 text-primary-600 bg-dark-700 border-dark-600 rounded focus:ring-primary-500"
                  />
                  <span className="text-dark-300">Word Wrap</span>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.minimap}
                    onChange={(e) => handleSettingChange('minimap', e.target.checked)}
                    className="w-4 h-4 text-primary-600 bg-dark-700 border-dark-600 rounded focus:ring-primary-500"
                  />
                  <span className="text-dark-300">Minimap</span>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.lineNumbers}
                    onChange={(e) => handleSettingChange('lineNumbers', e.target.checked)}
                    className="w-4 h-4 text-primary-600 bg-dark-700 border-dark-600 rounded focus:ring-primary-500"
                  />
                  <span className="text-dark-300">Line Numbers</span>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.autoSave}
                    onChange={(e) => handleSettingChange('autoSave', e.target.checked)}
                    className="w-4 h-4 text-primary-600 bg-dark-700 border-dark-600 rounded focus:ring-primary-500"
                  />
                  <span className="text-dark-300">Auto Save</span>
                </label>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4">Actions</h2>
            
            <div className="flex space-x-4">
              <button
                onClick={resetSettings}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
              >
                Reset to Defaults
              </button>
              
              <button
                onClick={loadSettings}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
              >
                Reload Settings
              </button>
            </div>
          </div>

          {/* System Information */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4">System Information</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div>
                <div className="text-dark-400">Application Version</div>
                <div className="text-dark-100 font-mono">1.0.0</div>
              </div>
              
              <div>
                <div className="text-dark-400">Backend URL</div>
                <div className="text-dark-100 font-mono">http://localhost:8000</div>
              </div>
              
              <div>
                <div className="text-dark-400">Ollama URL (Current)</div>
                <div className="text-dark-100 font-mono">
                  {settings.useProxy ? settings.ollamaUrl : settings.ollamaDirectUrl}
                </div>
              </div>
              
              <div>
                <div className="text-dark-400">Environment</div>
                <div className="text-dark-100 font-mono">Development</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Settings;
