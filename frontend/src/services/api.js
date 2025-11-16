import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

class ApiService {
  static normalizePath(path = '.') {
    if (!path || path === '.' || path === './') {
      return '.';
    }
    return path.replace(/\\/g, '/');
  }

  static encodePath(path = '.') {
    const normalized = this.normalizePath(path);
    if (normalized === '.') {
      return '.';
    }
    return encodeURIComponent(normalized).replace(/%2F/g, '/');
  }

  static async request(method, url, data = null, config = {}) {
    try {
      const response = await axios({
        method,
        url: `${API_BASE_URL}${url}`,
        data,
        signal: config.signal,
        ...config
      });
      return response.data;
    } catch (error) {
      if (error.name === 'CanceledError' || error.name === 'AbortError') {
        throw error;
      }
      console.error(`API ${method} ${url} failed:`, error);
      throw error;
    }
  }

  static async get(url, config = {}) {
    return this.request('GET', url, null, config);
  }

  static async post(url, data = null, config = {}) {
    return this.request('POST', url, data, config);
  }

  static async put(url, data = null, config = {}) {
    return this.request('PUT', url, data, config);
  }

  static async delete(url, config = {}) {
    return this.request('DELETE', url, null, config);
  }

  // Chat API
  static async sendMessage(message, context = {}, conversationHistory = [], options = {}) {
    const payload = {
      message,
      context,
      conversation_history: conversationHistory
    };

    if (options.mode) {
      payload.mode = options.mode;
    }

    if (options.metadata) {
      payload.metadata = options.metadata;
    }

    const config = {};
    if (options.signal) {
      config.signal = options.signal;
    }

    return this.post('/api/chat/send', payload, config);
  }

  static async getModels() {
    return this.get('/api/chat/models');
  }

  static async selectModel(modelName) {
    return this.post(`/api/chat/models/${modelName}/select`);
  }

  static async getChatStatus() {
    return this.get('/api/chat/status');
  }

  static async previewAgentStatuses(message, context = {}) {
    return this.post('/api/chat/status-preview', {
      message,
      context
    });
  }

  // File API
  static async listDirectory(path = '.') {
    const encodedPath = this.encodePath(path);
    return this.get(`/api/files/list/${encodedPath}`);
  }

  static async readFile(path) {
    const encodedPath = this.encodePath(path);
    return this.get(`/api/files/read/${encodedPath}`);
  }

  static async writeFile(path, content) {
    const encodedPath = this.encodePath(path);
    return this.post(`/api/files/write/${encodedPath}`, { content });
  }

  static async createDirectory(path) {
    const encodedPath = this.encodePath(path);
    return this.post(`/api/files/create-directory/${encodedPath}`);
  }

  static async deleteFile(path) {
    const encodedPath = this.encodePath(path);
    return this.delete(`/api/files/delete/${encodedPath}`);
  }

  static async searchFiles(query, path = '.') {
    const normalizedPath = this.normalizePath(path);
    const encodedQuery = encodeURIComponent(query);
    const encodedPath = encodeURIComponent(normalizedPath);
    return this.get(`/api/files/search/${encodedQuery}?path=${encodedPath}`);
  }

  static async getFileInfo(path) {
    const encodedPath = this.encodePath(path);
    return this.get(`/api/files/info/${encodedPath}`);
  }

  static async getFileTree(path = '.', maxDepth = 6) {
    const encodedPath = this.encodePath(path);
    return this.get(`/api/files/tree/${encodedPath}?max_depth=${maxDepth}`);
  }

  // Code API
  static async analyzeCode(path) {
    const encodedPath = this.encodePath(path);
    return this.post(`/api/code/analyze/${encodedPath}`);
  }

  static async generateCode(prompt, language = 'python', context = {}, maxLength = 1000) {
    return this.post('/api/code/generate', {
      prompt,
      language,
      context,
      max_length: maxLength
    });
  }

  static async searchCode(query, path = '.', language = null, maxResults = 10) {
    return this.post('/api/code/search', {
      query,
      path,
      language,
      max_results: maxResults
    });
  }

  static async getSupportedLanguages() {
    return this.get('/api/code/languages');
  }

  static async refactorCode(path, refactorType) {
    const encodedPath = this.encodePath(path);
    return this.post(`/api/code/refactor/${encodedPath}`, { refactor_type: refactorType });
  }

  static async getCodeSuggestions(path, lineNumber) {
    const encodedPath = this.encodePath(path);
    return this.get(`/api/code/suggestions/${encodedPath}?line_number=${lineNumber}`);
  }

  // Settings API
  static async getSettings() {
    return this.get('/api/settings/settings');
  }

  static async updateSettings(settings) {
    return this.put('/api/settings/settings', settings);
  }

  static async testOllamaConnection() {
    return this.post('/api/settings/test-connection');
  }

  // Terminal API
  static async ensureTerminalSession(sessionId = null) {
    return this.post('/api/terminal/session', { session_id: sessionId });
  }

  static async runTerminalCommand(command, sessionId, timeout = 120, env = null) {
    return this.post('/api/terminal/command', {
      command,
      session_id: sessionId,
      timeout,
      env,
    });
  }
}

export { ApiService };
