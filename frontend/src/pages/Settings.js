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
  X,
  Palette
} from 'lucide-react';
import { ApiService } from '../services/api';
import { getAvailableThemes, applyTheme } from '../utils/themeManager';
import toast from 'react-hot-toast';

const HF_DEFAULT_BASE_URL = 'https://api-inference.huggingface.co';

const Settings = () => {
  const [settings, setSettings] = useState({
    currentModel: 'codellama',
    availableModels: [],
    ollamaUrl: 'http://localhost:5000',
    ollamaDirectUrl: 'http://localhost:11434',
    useProxy: true,
    provider: 'ollama',
    hfModel: 'meta-llama/Llama-3.1-8B-Instruct',
    hfBaseUrl: '',
    hfApiKeySet: false,
    // OpenRouter
    openrouterModel: 'openrouter/auto',
    openrouterBaseUrl: 'https://openrouter.ai/api/v1',
    openrouterApiKeySet: false,
    autoSave: true,
    theme: 'dark',
    fontSize: 14,
    tabSize: 2,
    wordWrap: true,
    minimap: true,
    lineNumbers: true,
  });
  
  const [hfApiKeyInput, setHfApiKeyInput] = useState('');
  const [hfApiKeyDirty, setHfApiKeyDirty] = useState(false);
  const [openrouterApiKeyInput, setOpenrouterApiKeyInput] = useState('');
  const [openrouterApiKeyDirty, setOpenrouterApiKeyDirty] = useState(false);
  const normalizeHfBaseUrlValue = (value) => {
    if (!value) {
      return '';
    }
    const trimmed = value.trim();
    return trimmed.toLowerCase() === HF_DEFAULT_BASE_URL.toLowerCase() ? '' : trimmed;
  };
  const [isSaving, setIsSaving] = useState(false);
  
  const [connectionStatus, setConnectionStatus] = useState({
    backend: false,
    providerConnected: false,
    providerLabel: 'Ollama',
  });
  
  const [isLoading, setIsLoading] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [availableThemes, setAvailableThemes] = useState([]);
  const [activeThemeId, setActiveThemeId] = useState(null);
  const [isLoadingThemes, setIsLoadingThemes] = useState(false);

  useEffect(() => {
    loadSettings();
    checkConnections();
    loadThemes();
  }, []);

  const loadThemes = async () => {
    setIsLoadingThemes(true);
    try {
      const themes = await getAvailableThemes();
      setAvailableThemes(themes);
      
      // Get active theme
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
    } finally {
      setIsLoadingThemes(false);
    }
  };

  const handleThemeChange = async (themeId) => {
    try {
      const success = await applyTheme(themeId);
      if (success) {
        setActiveThemeId(themeId);
        toast.success('Theme applied successfully');
      } else {
        toast.error('Failed to apply theme');
      }
    } catch (error) {
      console.error('Error applying theme:', error);
      toast.error('Failed to apply theme');
    }
  };

  const loadSettings = async () => {
    try {
      const [modelsResponse, statusResponse, backendSettings] = await Promise.all([
        ApiService.getModels(),
        ApiService.getChatStatus(),
        ApiService.getSettings().catch(() => null)
      ]);
      const normalizedHfBaseUrl = backendSettings ? normalizeHfBaseUrlValue(backendSettings.hf_base_url) : '';
      
      setSettings(prev => ({
        ...prev,
        availableModels: modelsResponse.models || [],
        currentModel: statusResponse.current_model || 'codellama',
        ...(backendSettings && {
          ollamaUrl: backendSettings.ollama_url || prev.ollamaUrl,
          ollamaDirectUrl: backendSettings.ollama_direct_url || prev.ollamaDirectUrl,
          useProxy: backendSettings.use_proxy !== undefined ? backendSettings.use_proxy : prev.useProxy,
          provider: backendSettings.provider || prev.provider,
          hfModel: backendSettings.hf_model || prev.hfModel,
          hfBaseUrl: normalizedHfBaseUrl ?? prev.hfBaseUrl,
          hfApiKeySet: backendSettings.hf_api_key_set ?? prev.hfApiKeySet,
          openrouterModel: backendSettings.openrouter_model || prev.openrouterModel,
          openrouterBaseUrl: backendSettings.openrouter_base_url || prev.openrouterBaseUrl,
          openrouterApiKeySet: backendSettings.openrouter_api_key_set ?? prev.openrouterApiKeySet,
        })
      }));
      setHfApiKeyInput('');
      setHfApiKeyDirty(false);
      setOpenrouterApiKeyInput('');
      setOpenrouterApiKeyDirty(false);
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
        providerConnected: typeof ollamaResponse.provider_connected === 'boolean'
          ? ollamaResponse.provider_connected
          : !!ollamaResponse.ollama_connected,
        providerLabel:
          ollamaResponse.provider === 'huggingface'
            ? 'Hugging Face'
            : (ollamaResponse.provider === 'openrouter' ? 'OpenRouter' : 'Ollama')
      }));
    } catch (error) {
      console.error('Error checking connections:', error);
      setConnectionStatus({
        backend: false,
        providerConnected: false,
        providerLabel: 'Ollama'
      });
    } finally {
      setIsLoading(false);
    }
  };

  const testProviderConnection = async () => {
    setIsTestingConnection(true);
    try {
      const response = await ApiService.testOllamaConnection();
      if (response.connected) {
        toast.success(response.message || 'Provider connection successful!');
        setConnectionStatus(prev => ({
          ...prev,
          providerConnected: true,
          providerLabel:
            settings.provider === 'huggingface'
              ? 'Hugging Face'
              : (settings.provider === 'openrouter' ? 'OpenRouter' : 'Ollama')
        }));
        // Reload models if connection successful
        if (response.available_models) {
          setSettings(prev => ({
            ...prev,
            availableModels: response.available_models
          }));
        }
      } else {
        toast.error(response.message || 'Provider is not accessible');
        setConnectionStatus(prev => ({
          ...prev,
          providerConnected: false,
          providerLabel:
            settings.provider === 'huggingface'
              ? 'Hugging Face'
              : (settings.provider === 'openrouter' ? 'OpenRouter' : 'Ollama')
        }));
      }
    } catch (error) {
      console.error('Error testing provider connection:', error);
      toast.error('Failed to connect to provider');
      setConnectionStatus(prev => ({
        ...prev,
        providerConnected: false,
        providerLabel:
          settings.provider === 'huggingface'
            ? 'Hugging Face'
            : (settings.provider === 'openrouter' ? 'OpenRouter' : 'Ollama')
      }));
    } finally {
      setIsTestingConnection(false);
    }
  };
  
  const saveProviderSettings = async ({ skipTest = false, silent = false } = {}) => {
    setIsSaving(true);
    try {
      const payload = {
        provider: settings.provider,
        ollama_url: settings.ollamaUrl,
        ollama_direct_url: settings.ollamaDirectUrl,
        use_proxy: settings.useProxy,
      };

      if (settings.provider === 'huggingface') {
        payload.hf_model = settings.hfModel;
        payload.hf_base_url = normalizeHfBaseUrlValue(settings.hfBaseUrl);
      }
      if (settings.provider === 'openrouter') {
        payload.openrouter_model = settings.openrouterModel;
        payload.openrouter_base_url = settings.openrouterBaseUrl;
      }

      if (hfApiKeyDirty) {
        payload.hf_api_key = hfApiKeyInput;
      }
      if (openrouterApiKeyDirty) {
        payload.openrouter_api_key = openrouterApiKeyInput;
      }

      await ApiService.updateSettings(payload);

      if (hfApiKeyDirty) {
        setSettings(prev => ({
          ...prev,
          hfApiKeySet: !!hfApiKeyInput
        }));
        setHfApiKeyDirty(false);
        setHfApiKeyInput('');
      }
      if (openrouterApiKeyDirty) {
        setSettings(prev => ({
          ...prev,
          openrouterApiKeySet: !!openrouterApiKeyInput
        }));
        setOpenrouterApiKeyDirty(false);
        setOpenrouterApiKeyInput('');
      }

      if (!silent) {
        toast.success('Provider settings saved successfully!');
      }

      if (!skipTest) {
        await testProviderConnection();
      }

      return true;
    } catch (error) {
      console.error('Error saving provider settings:', error);
      toast.error(error.response?.data?.detail || 'Failed to save provider settings');
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async () => {
    const saved = await saveProviderSettings({ skipTest: true, silent: true });
    if (!saved) {
      return;
    }
    await testProviderConnection();
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
    setSettings(prev => {
      const next = { ...prev, [key]: value };
      if (key === 'hfModel' && prev.provider === 'huggingface') {
        next.currentModel = value;
      }
      if (key === 'openrouterModel' && prev.provider === 'openrouter') {
        next.currentModel = value;
      }
      if (key === 'provider') {
        if (value === 'huggingface') {
          next.currentModel = next.hfModel;
        } else if (value === 'openrouter') {
          next.currentModel = next.openrouterModel;
        } else {
          next.currentModel = prev.currentModel;
        }
      }
      localStorage.setItem('offline-ai-settings', JSON.stringify(next));
      return next;
    });
    if (key === 'provider') {
      setConnectionStatus(prev => ({
        ...prev,
        providerLabel:
          value === 'huggingface'
            ? 'Hugging Face'
            : (value === 'openrouter' ? 'OpenRouter' : 'Ollama')
      }));
    }
  };

  const resetSettings = async () => {
    const defaultSettings = {
      currentModel: 'codellama',
      availableModels: [],
      ollamaUrl: 'http://localhost:5000',
      ollamaDirectUrl: 'http://localhost:11434',
      useProxy: true,
      provider: 'ollama',
      hfModel: 'meta-llama/Llama-3.1-8B-Instruct',
      hfBaseUrl: 'https://api-inference.huggingface.co',
      hfApiKeySet: false,
      openrouterModel: 'openrouter/auto',
      openrouterBaseUrl: 'https://openrouter.ai/api/v1',
      openrouterApiKeySet: false,
      autoSave: true,
      theme: 'dark',
      fontSize: 14,
      tabSize: 2,
      wordWrap: true,
      minimap: true,
      lineNumbers: true,
    };
    setSettings(defaultSettings);
    setHfApiKeyInput('');
    setHfApiKeyDirty(false);
    localStorage.setItem('offline-ai-settings', JSON.stringify(defaultSettings));
    
    // Also reset backend settings
    try {
      await ApiService.updateSettings({
        provider: defaultSettings.provider,
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
                    <div className="font-medium text-dark-100">{connectionStatus.providerLabel}</div>
                    <div className={`text-sm ${getStatusColor(connectionStatus.providerConnected)}`}>
                      {getStatusText(connectionStatus.providerConnected)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {getStatusIcon(connectionStatus.providerConnected)}
                  <button
                    onClick={testProviderConnection}
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

          {/* Model Provider Configuration */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Database className="w-5 h-5" />
              <span>Model Provider</span>
            </h2>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Provider
                </label>
                <select
                  value={settings.provider}
                  onChange={(e) => handleSettingChange('provider', e.target.value)}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="ollama">Ollama (local)</option>
                  <option value="huggingface">Hugging Face Inference API</option>
                  <option value="openrouter">OpenRouter (hosted)</option>
                </select>
                <p className="text-xs text-dark-400 mt-1">
                  Choose between your local Ollama runtime, Hugging Face Inference API, or OpenRouter.
                </p>
              </div>

              {settings.provider === 'ollama' ? (
                <>
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
                </>
              ) : settings.provider === 'huggingface' ? (
                <>
                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      Hugging Face API Base URL
                    </label>
                    <input
                      type="text"
                      value={settings.hfBaseUrl}
                      onChange={(e) => handleSettingChange('hfBaseUrl', e.target.value)}
                      placeholder="https://api-inference.huggingface.co"
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
              Leave blank to use the default Hugging Face endpoint ({HF_DEFAULT_BASE_URL}).
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      Model ID
                    </label>
                    <input
                      type="text"
                      value={settings.hfModel}
                      onChange={(e) => handleSettingChange('hfModel', e.target.value)}
                      placeholder="meta-llama/Llama-3.1-8B-Instruct"
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
                      Any chat-completion compatible model hosted on Hugging Face.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      API Key
                    </label>
                    <input
                      type="password"
                      value={hfApiKeyInput}
                      onChange={(e) => {
                        setHfApiKeyInput(e.target.value);
                        setHfApiKeyDirty(true);
                      }}
                      placeholder="hf_xxx..."
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
                      {settings.hfApiKeySet
                        ? 'An API key is stored securely on the backend. Leave blank to keep it.'
                        : 'No API key stored yet. Add one to enable Hugging Face access.'}
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      OpenRouter API Base URL
                    </label>
                    <input
                      type="text"
                      value={settings.openrouterBaseUrl}
                      onChange={(e) => handleSettingChange('openrouterBaseUrl', e.target.value)}
                      placeholder="https://openrouter.ai/api/v1"
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
                      Usually leave as the default OpenRouter endpoint.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      OpenRouter Model ID
                    </label>
                    <input
                      type="text"
                      value={settings.openrouterModel}
                      onChange={(e) => handleSettingChange('openrouterModel', e.target.value)}
                      placeholder="openrouter/auto or specific model id"
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
                      Any chat-completion compatible model available in your OpenRouter account.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-dark-300 mb-2">
                      OpenRouter API Key
                    </label>
                    <input
                      type="password"
                      value={openrouterApiKeyInput}
                      onChange={(e) => {
                        setOpenrouterApiKeyInput(e.target.value);
                        setOpenrouterApiKeyDirty(true);
                      }}
                      placeholder={settings.openrouterApiKeySet ? '••••••••••••••••' : 'sk-or-... (kept on backend only)'}
                      className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <p className="text-xs text-dark-400 mt-1">
                      {settings.openrouterApiKeySet
                        ? 'An API key is stored securely on the backend. Leave blank to keep it.'
                        : 'No API key stored yet. Add one to enable OpenRouter access.'}
                    </p>
                  </div>
                </>
              )}

              <div className="flex space-x-3">
                <button
                  onClick={saveProviderSettings}
                  disabled={isSaving}
                  className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded transition-colors disabled:opacity-50 flex items-center space-x-2"
                >
                  {isSaving ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Saving...</span>
                    </>
                  ) : (
                    <span>Save Provider Settings</span>
                  )}
                </button>
                <button
                  onClick={handleTestConnection}
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
                    disabled={settings.provider === 'huggingface' || settings.provider === 'openrouter'}
                    className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    {settings.availableModels.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                  {settings.provider === 'huggingface' && (
                    <p className="text-xs text-dark-400 mt-2">
                      Set the Hugging Face model ID in the provider section above.
                    </p>
                  )}
                  {settings.provider === 'openrouter' && (
                    <p className="text-xs text-dark-400 mt-2">
                      Set the OpenRouter model ID in the provider section above.
                    </p>
                  )}
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

          {/* Theme Settings */}
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6">
            <h2 className="text-xl font-semibold text-dark-50 mb-4 flex items-center space-x-2">
              <Palette className="w-5 h-5" />
              <span>Themes</span>
            </h2>
            
            <div className="space-y-4">
              {isLoadingThemes ? (
                <div className="text-sm text-dark-400">Loading themes...</div>
              ) : availableThemes.length === 0 ? (
                <div className="text-sm text-dark-400">
                  No themes installed. Install theme extensions from the Extensions panel.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {availableThemes.map((theme) => (
                    <button
                      key={theme.id}
                      onClick={() => handleThemeChange(theme.id)}
                      className={`p-4 rounded-lg border transition-colors text-left ${
                        activeThemeId === theme.id
                          ? 'bg-primary-600 border-primary-500 text-white'
                          : 'bg-dark-700 border-dark-600 text-dark-300 hover:border-dark-500'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium">{theme.label || theme.extension_name || theme.id}</div>
                          {theme.extension_name && (
                            <div className="text-xs opacity-75 mt-1">{theme.extension_name}</div>
                          )}
                        </div>
                        {activeThemeId === theme.id && (
                          <Check className="w-5 h-5" />
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
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
