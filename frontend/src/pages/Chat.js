import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2 } from 'lucide-react';
import { ApiService } from '../services/api';
import { formatMessageContent, copyToClipboard } from '../utils/messageFormatter';
import toast from 'react-hot-toast';

const Chat = () => {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationHistory, setConversationHistory] = useState([]);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setConversationHistory(prev => [...prev, userMessage]);
    setInputMessage('');
    setIsLoading(true);

    try {
      const response = await ApiService.sendMessage(
        inputMessage,
        { current_page: 'chat' },
        conversationHistory
      );

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.response,
        timestamp: response.timestamp
      };

      setMessages(prev => [...prev, assistantMessage]);
      setConversationHistory(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      toast.error('Failed to send message. Please check your connection.');
      
      const errorMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please make sure Ollama is running and try again.',
        timestamp: new Date().toISOString(),
        isError: true
      };
      
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Add event listeners for code copy buttons after rendering
  useEffect(() => {
    const copyButtons = document.querySelectorAll('.copy-code-btn');
    copyButtons.forEach(button => {
      button.addEventListener('click', () => {
        const codeId = button.getAttribute('data-code-id');
        const codeElement = document.getElementById(codeId);
        if (codeElement) {
          copyToClipboard(codeElement.value, button);
        }
      });
    });
  }, [messages]);

  const clearChat = () => {
    setMessages([]);
    setConversationHistory([]);
    toast.success('Chat cleared');
  };

  return (
    <div className="flex flex-col h-full bg-dark-900">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-dark-700 bg-dark-800">
        <div className="flex items-center space-x-3">
          <Bot className="w-6 h-6 text-primary-500" />
          <h1 className="text-xl font-semibold text-dark-50">AI Chat</h1>
        </div>
        <button
          onClick={clearChat}
          className="px-3 py-1 text-sm text-dark-400 hover:text-dark-200 transition-colors"
        >
          Clear Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Bot className="w-16 h-16 text-dark-600 mb-4" />
            <h2 className="text-xl font-semibold text-dark-300 mb-2">
              Welcome to Offline AI Agent
            </h2>
            <p className="text-dark-400 max-w-md">
              I'm your local AI coding assistant. Ask me to help with code generation, 
              analysis, debugging, or any programming questions. I work entirely offline!
            </p>
            <div className="mt-6 grid grid-cols-1 gap-3 max-w-md">
              <button
                onClick={() => setInputMessage("Help me write a Python function to sort a list")}
                className="p-3 text-left bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-700 transition-colors"
              >
                <div className="font-medium text-dark-200">Code Generation</div>
                <div className="text-sm text-dark-400">Generate code from descriptions</div>
              </button>
              <button
                onClick={() => setInputMessage("Explain this code: def fibonacci(n): return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)")}
                className="p-3 text-left bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-700 transition-colors"
              >
                <div className="font-medium text-dark-200">Code Explanation</div>
                <div className="text-sm text-dark-400">Understand complex code</div>
              </button>
              <button
                onClick={() => setInputMessage("Help me debug this error: 'list' object has no attribute 'append'")}
                className="p-3 text-left bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-700 transition-colors"
              >
                <div className="font-medium text-dark-200">Debugging</div>
                <div className="text-sm text-dark-400">Fix errors and issues</div>
              </button>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex space-x-3 ${
                message.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {message.role === 'assistant' && (
                <div className="flex-shrink-0">
                  <div className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center">
                    <Bot className="w-4 h-4 text-white" />
                  </div>
                </div>
              )}
              
              <div
                className={`max-w-3xl px-4 py-3 rounded-lg ${
                  message.role === 'user'
                    ? 'bg-primary-600 text-white'
                    : message.isError
                    ? 'bg-red-900/20 border border-red-700 text-red-300'
                    : 'bg-dark-800 border border-dark-700 text-dark-100'
                }`}
              >
                <div
                  className="prose prose-invert max-w-none"
                  dangerouslySetInnerHTML={{
                    __html: formatMessageContent(message.content)
                  }}
                />
                <div className="text-xs opacity-70 mt-2">
                  {new Date(message.timestamp).toLocaleTimeString()}
                </div>
              </div>

              {message.role === 'user' && (
                <div className="flex-shrink-0">
                  <div className="w-8 h-8 bg-dark-600 rounded-full flex items-center justify-center">
                    <User className="w-4 h-4 text-dark-300" />
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="flex space-x-3 justify-start">
            <div className="flex-shrink-0">
              <div className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center">
                <Bot className="w-4 h-4 text-white" />
              </div>
            </div>
            <div className="bg-dark-800 border border-dark-700 rounded-lg px-4 py-3">
              <div className="flex items-center space-x-2">
                <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
                <span className="text-dark-300">AI is thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-dark-700 bg-dark-800">
        <form onSubmit={handleSendMessage} className="flex space-x-3">
          <div className="flex-1">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Ask me anything about coding..."
              className="w-full px-4 py-3 bg-dark-700 border border-dark-600 rounded-lg text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading}
            />
          </div>
          <button
            type="submit"
            disabled={!inputMessage.trim() || isLoading}
            className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center space-x-2"
          >
            <Send className="w-4 h-4" />
            <span>Send</span>
          </button>
        </form>
      </div>
    </div>
  );
};

export default Chat;
