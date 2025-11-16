import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Layout from './components/Layout';
import Chat from './pages/Chat';
import FileExplorer from './pages/FileExplorer';
import CodeEditor from './pages/CodeEditor';
import Settings from './pages/Settings';
import { ApiService } from './services/api';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [currentModel, setCurrentModel] = useState('codellama');
  const [availableModels, setAvailableModels] = useState([]);

  useEffect(() => {
    checkConnection();
    loadModels();
  }, []);

  const checkConnection = async () => {
    try {
      const response = await ApiService.get('/health');
      setIsConnected(response.status === 'healthy');
    } catch (error) {
      console.error('Connection check failed:', error);
      setIsConnected(false);
    }
  };

  const loadModels = async () => {
    try {
      const response = await ApiService.get('/api/chat/models');
      setAvailableModels(response.models || []);
    } catch (error) {
      console.error('Failed to load models:', error);
    }
  };

  const selectModel = async (modelName) => {
    try {
      await ApiService.post(`/api/chat/models/${modelName}/select`);
      setCurrentModel(modelName);
    } catch (error) {
      console.error('Failed to select model:', error);
    }
  };

  return (
    <Router>
      <div className="App min-h-screen bg-dark-900 text-dark-50">
        <Layout 
          isConnected={isConnected}
          currentModel={currentModel}
          availableModels={availableModels}
          onModelSelect={selectModel}
        >
          <Routes>
            <Route path="/" element={<Chat />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/files" element={<FileExplorer />} />
            <Route path="/editor" element={<CodeEditor />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
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
    </Router>
  );
}

export default App;
