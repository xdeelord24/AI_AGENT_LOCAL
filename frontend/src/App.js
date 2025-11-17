import React, { useState, useEffect, useCallback } from 'react';
import { Toaster } from 'react-hot-toast';
import IDELayout from './components/IDELayout';
import { ApiService } from './services/api';

const CONNECTION_CHECK_INTERVAL_MS = 5000;

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [currentModel, setCurrentModel] = useState('codellama');
  const [availableModels, setAvailableModels] = useState([]);

  const checkConnection = useCallback(async () => {
    try {
      const response = await ApiService.get('/health');
      setIsConnected(response.status === 'healthy');
    } catch (error) {
      console.error('Connection check failed:', error);
      setIsConnected(false);
    }
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const response = await ApiService.get('/api/chat/models');
      setAvailableModels(response.models || []);
    } catch (error) {
      console.error('Failed to load models:', error);
    }
  }, []);

  useEffect(() => {
    let intervalId;

    const startMonitoring = () => {
      checkConnection();
      intervalId = setInterval(checkConnection, CONNECTION_CHECK_INTERVAL_MS);
    };

    startMonitoring();

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [checkConnection]);

  useEffect(() => {
    if (isConnected) {
      loadModels();
    }
  }, [isConnected, loadModels]);

  const selectModel = async (modelName) => {
    try {
      await ApiService.post(`/api/chat/models/${modelName}/select`);
      setCurrentModel(modelName);
    } catch (error) {
      console.error('Failed to select model:', error);
    }
  };

  return (
    <div className="App min-h-screen bg-dark-900 text-dark-50">
      <IDELayout 
        isConnected={isConnected}
        currentModel={currentModel}
        availableModels={availableModels}
        onModelSelect={selectModel}
      />
      <Toaster 
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: '#1e293b',
            color: '#f1f5f9',
            border: '1px solid #334155',
          },
        }}
      />
    </div>
  );
}

export default App;
