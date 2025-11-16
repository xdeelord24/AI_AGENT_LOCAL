import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

class ApiService {
  static async request(method, url, data = null, config = {}) {
    try {
      const response = await axios({
        method,
        url: `${API_BASE_URL}${url}`,
        data,
        ...config
      });
      return response.data;
    } catch (error) {
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
  static async sendMessage(message, context = {}, conversationHistory = []) {
    return this.post('/api/chat/send', {
      message,
      context,
      conversation_history: conversationHistory
    });
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

  // File API
  static async listDirectory(path = '.') {
    return this.get(`/api/files/list/${path}`);
  }

  static async readFile(path) {
    return this.get(`/api/files/read/${path}`);
  }

  static async writeFile(path, content) {
    return this.post(`/api/files/write/${path}`, { content });
  }

  static async createDirectory(path) {
    return this.post(`/api/files/create-directory/${path}`);
  }

  static async deleteFile(path) {
    return this.delete(`/api/files/delete/${path}`);
  }

  static async searchFiles(query, path = '.') {
    return this.get(`/api/files/search/${query}?path=${path}`);
  }

  static async getFileInfo(path) {
    return this.get(`/api/files/info/${path}`);
  }

  // Code API
  static async analyzeCode(path) {
    return this.post(`/api/code/analyze/${path}`);
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
    return this.post(`/api/code/refactor/${path}`, { refactor_type: refactorType });
  }

  static async getCodeSuggestions(path, lineNumber) {
    return this.get(`/api/code/suggestions/${path}?line_number=${lineNumber}`);
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
}

export { ApiService };
