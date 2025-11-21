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
    // Extract custom options that aren't axios config
    const { suppress404, ...axiosConfig } = config;
    
    try {
      const response = await axios({
        method,
        url: `${API_BASE_URL}${url}`,
        data,
        ...axiosConfig
      });
      return response.data;
    } catch (error) {
      if (error.name === 'CanceledError' || error.name === 'AbortError') {
        throw error;
      }
      // Suppress console errors for expected 404s (e.g., when checking for non-existent sessions)
      // Only log unexpected errors
      if (error.response?.status !== 404 || suppress404 !== true) {
        console.error(`API ${method} ${url} failed:`, error);
      }
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

  static async submitFeedback({ conversationId, messageId, rating, comment = null }) {
    return this.post('/api/chat/feedback', {
      conversation_id: conversationId,
      message_id: messageId,
      rating,
      comment,
    });
  }

  // Chat Sessions API
  static async createChatSession(title, messages, conversationId = null) {
    return this.post('/api/chat/sessions', {
      title,
      messages,
      conversation_id: conversationId
    });
  }

  static async listChatSessions() {
    return this.get('/api/chat/sessions');
  }

  static async getChatSession(sessionId) {
    return this.get(`/api/chat/sessions/${sessionId}`);
  }

  static async getChatSessionByConversationId(conversationId) {
    return this.get(`/api/chat/sessions/by-conversation/${conversationId}`, { suppress404: true });
  }

  static async updateChatSession(sessionId, title = null, messages = null) {
    return this.put(`/api/chat/sessions/${sessionId}`, {
      title,
      messages
    });
  }

  static async deleteChatSession(sessionId) {
    return this.delete(`/api/chat/sessions/${sessionId}`);
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

  static async movePath(sourcePath, destinationPath, overwrite = false) {
    return this.post('/api/files/move', {
      source_path: this.normalizePath(sourcePath),
      destination_path: this.normalizePath(destinationPath),
      overwrite,
    });
  }

  static async copyPath(sourcePath, destinationPath, overwrite = false) {
    return this.post('/api/files/copy', {
      source_path: this.normalizePath(sourcePath),
      destination_path: this.normalizePath(destinationPath),
      overwrite,
    });
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

  static async getCodeCompletion(filePath, content, cursorLine, cursorColumn, language) {
    return this.post('/api/code/completion', {
      file_path: filePath,
      content,
      cursor_line: cursorLine,
      cursor_column: cursorColumn,
      language
    });
  }

  // Settings API
  static async getSettings() {
    // Backend mounts settings router at /api/settings
    return this.get('/api/settings');
  }

  static async updateSettings(settings) {
    // Backend expects PUT /api/settings
    return this.put('/api/settings', settings);
  }

  static async testOllamaConnection() {
    return this.post('/api/settings/test-connection');
  }

  // Terminal API
  static async ensureTerminalSession(sessionId = null, basePath = null) {
    const payload = { session_id: sessionId };
    if (basePath) {
      payload.base_path = basePath;
    }
    return this.post('/api/terminal/session', payload);
  }

  static async runTerminalCommand(command, sessionId, timeout = 120, env = null) {
    return this.post('/api/terminal/command', {
      command,
      session_id: sessionId,
      timeout,
      env,
    });
  }

  static async runTerminalCommandStream({
    command,
    sessionId,
    timeout = 120,
    env = null,
    signal,
    onEvent,
  }) {
    if (typeof onEvent !== 'function') {
      throw new Error('runTerminalCommandStream requires an onEvent callback');
    }

    const response = await fetch(`${API_BASE_URL}/api/terminal/command/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/x-ndjson',
      },
      body: JSON.stringify({
        command,
        session_id: sessionId,
        timeout,
        env,
      }),
      signal,
    });

    if (!response.ok) {
      let detail;
      try {
        detail = await response.json();
      } catch {
        detail = null;
      }
      const message = detail?.detail || detail?.message || `Streaming failed (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      error.code =
        response.status === 404 ||
        response.status === 405 ||
        response.status === 501 ||
        response.status === 503
          ? 'STREAM_NOT_AVAILABLE'
          : 'STREAM_HTTP_ERROR';
      throw error;
    }

    if (!response.body || typeof response.body.getReader !== 'function') {
      const error = new Error('Streaming responses are not supported in this browser');
      error.code = 'STREAM_NOT_AVAILABLE';
      throw error;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const flushBuffer = async (force = false) => {
      let newlineIndex;
      while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
        const rawLine = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 1);
        const line = rawLine.trim();
        if (!line) {
          continue;
        }
        try {
          const payload = JSON.parse(line);
          await Promise.resolve(onEvent(payload));
        } catch (error) {
          console.warn('Skipping malformed terminal event chunk', rawLine, error);
        }
      }

      if (force) {
        const remaining = buffer.trim();
        buffer = '';
        if (remaining) {
          try {
            const payload = JSON.parse(remaining);
            await Promise.resolve(onEvent(payload));
          } catch (error) {
            console.warn('Skipping trailing malformed terminal event chunk', remaining, error);
          }
        }
      }
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        await flushBuffer(false);
      }
      buffer += decoder.decode();
      await flushBuffer(true);
    } finally {
      if (typeof reader.releaseLock === 'function') {
        reader.releaseLock();
      }
    }
  }

  static async stopTerminalCommand(sessionId) {
    return this.post('/api/terminal/interrupt', {
      session_id: sessionId,
    });
  }

  static async completeTerminalInput(command, sessionId, cursorPosition = null) {
    return this.post('/api/terminal/complete', {
      command,
      session_id: sessionId,
      cursor_position: cursorPosition,
    });
  }
}

export { ApiService };
