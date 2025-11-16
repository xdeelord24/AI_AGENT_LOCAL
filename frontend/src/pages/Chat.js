import React, { useState, useRef, useEffect, useCallback } from 'react';
import { 
  Send, Bot, User, Loader2, Clock, MoreVertical,
  ChevronDown, AtSign, Globe, Image as ImageIcon, Monitor,
  Infinity, Workflow
} from 'lucide-react';
import { ApiService } from '../services/api';
import { formatMessageContent, initializeCopyCodeListeners } from '../utils/messageFormatter';
import toast from 'react-hot-toast';

const MAX_FILE_SNIPPET = 5000;

const extractMentionPaths = (text = '') => {
  const regex = /@([^\s]+)/g;
  const matches = new Set();
  let match;
  while ((match = regex.exec(text)) !== null) {
    let mention = match[1];
    mention = mention.replace(/[)\],.?!"'`]+$/g, '');
    mention = mention.replace(/^\[(.*)\]$/, '$1');
    mention = mention.replace(/\\+/g, '/');
    if (mention.startsWith('./')) {
      mention = mention.slice(2);
    }
    if (mention.startsWith('/')) {
      mention = mention.slice(1);
    }
    if (mention) {
      matches.add(mention);
    }
  }
  return Array.from(matches);
};

const tryReadFile = async (path) => {
  if (!path) return null;
  const variations = [];
  const normalized = path.replace(/\\/g, '/');
  const trimmed = normalized.replace(/^\.?\/*/, '');
  variations.push(normalized);
  variations.push(trimmed);
  if (!trimmed.startsWith('./')) {
    variations.push(`./${trimmed}`);
  }

  for (const candidate of variations) {
    try {
      const data = await ApiService.readFile(candidate);
      return {
        path: candidate,
        name: candidate.split('/').pop() || candidate,
        content: data?.content || ''
      };
    } catch (error) {
      continue;
    }
  }
  return null;
};

const loadMentionedFiles = async (mentions = []) => {
  const files = [];
  for (const mention of mentions) {
    try {
      let fileData = await tryReadFile(mention);
      if (!fileData) {
        const baseName = mention.split('/').pop();
        if (baseName) {
          try {
            const searchResults = await ApiService.searchFiles(baseName);
            const candidate = searchResults?.results?.find((result) =>
              result.path && result.name && result.name.toLowerCase().includes(baseName.toLowerCase())
            );
            if (candidate?.path) {
              fileData = await tryReadFile(candidate.path);
            }
          } catch (searchError) {
            // Ignore search errors, fallback to next mention
          }
        }
      }
      if (fileData) {
        files.push(fileData);
      }
    } catch (error) {
      console.warn(`Failed to load context for mention: ${mention}`, error);
    }
  }
  return files;
};

const Chat = () => {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [composerInput, setComposerInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationHistory, setConversationHistory] = useState([]);
  const [agentMode, setAgentMode] = useState('Agent');
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [pastChats] = useState([
    { id: 1, title: 'Enhance UI with AI features', time: '2m' },
    { id: 2, title: 'Fix code generation for even o...', time: '20m' },
    { id: 3, title: 'Fix code generation for even o...', time: '44m' }
  ]);
  const messagesEndRef = useRef(null);
  const agentStatusTimersRef = useRef([]);

  const planStatusStyles = {
    completed: 'border-green-700 bg-green-500/10 text-green-300',
    in_progress: 'border-primary-600 bg-primary-600/10 text-primary-300',
    pending: 'border-dark-600 bg-dark-800/80 text-dark-200',
    blocked: 'border-red-700 bg-red-600/10 text-red-300'
  };

  const [agentStatuses, setAgentStatuses] = useState([]);

  const PlanCard = ({ plan }) => {
    if (!plan) return null;

    const summary = plan.summary || plan.thoughts || plan.description;
    const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];

    return (
      <div className="mt-3 bg-dark-900/60 border border-dark-700 rounded-2xl p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-dark-400">
          <Workflow className="w-3.5 h-3.5" />
          <span>AI plan</span>
        </div>
        {summary && <p className="text-sm text-dark-100">{summary}</p>}
        {tasks.length > 0 && (
          <div className="space-y-1">
            {tasks.slice(0, 6).map((task, idx) => {
              const statusKey = (task.status || 'pending').toLowerCase();
              const statusClass = planStatusStyles[statusKey] || planStatusStyles.pending;
              return (
                <div
                  key={task.id || `${task.title || 'task'}-${idx}`}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl bg-dark-800/70 text-sm text-dark-100"
                >
                  <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${statusClass}`}>
                    {statusKey.replace('_', ' ')}
                  </span>
                  <div className="flex-1">
                    <div className="font-medium">{task.title || task.summary || `Task ${idx + 1}`}</div>
                    {task.details && (
                      <div className="text-xs text-dark-300">
                        {task.details}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const clearAgentStatuses = useCallback(() => {
    agentStatusTimersRef.current.forEach((timerId) => clearTimeout(timerId));
    agentStatusTimersRef.current = [];
    setAgentStatuses([]);
  }, []);

  const scheduleAgentStatuses = useCallback((statuses = []) => {
    clearAgentStatuses();
    statuses.forEach((status) => {
      const timerId = setTimeout(() => {
        setAgentStatuses((prev) => {
          if (prev.find((item) => item.key === status.key)) {
            return prev;
          }
          return [...prev, status];
        });
      }, Math.max(status.delay_ms ?? 0, 0));
      agentStatusTimersRef.current.push(timerId);
    });
  }, [clearAgentStatuses]);

  useEffect(() => {
    return () => {
      clearAgentStatuses();
    };
  }, [clearAgentStatuses]);

  const applyFileOperations = useCallback(async (operations = []) => {
    const summary = { applied: [], failed: [] };

    if (!Array.isArray(operations) || operations.length === 0) {
      return summary;
    }

    toast.loading('Applying AI changes...', { id: 'ai-file-ops' });

    for (const operation of operations) {
      if (!operation?.type || !operation?.path) {
        summary.failed.push({
          type: operation?.type || 'unknown',
          path: operation?.path || 'unknown',
          error: new Error('Missing operation type or path'),
        });
        continue;
      }

      const opType = operation.type.toLowerCase();
      const targetPath = operation.path;
      const content = operation.content ?? '';

      try {
        if (opType === 'create_file') {
          await ApiService.writeFile(targetPath, content);
        } else if (opType === 'edit_file') {
          await ApiService.writeFile(targetPath, content);
        } else if (opType === 'delete_file') {
          await ApiService.deleteFile(targetPath);
        } else {
          summary.failed.push({
            type: opType,
            path: targetPath,
            error: new Error(`Unsupported operation: ${opType}`),
          });
          console.warn(`Unsupported file operation received: ${opType}`, operation);
          continue;
        }

        summary.applied.push({ type: opType, path: targetPath });
      } catch (error) {
        console.error(`Failed to ${opType} ${targetPath}`, error);
        summary.failed.push({ type: opType, path: targetPath, error });
        toast.error(`Failed to ${opType.replace('_', ' ')} ${targetPath}`);
      }
    }

    toast.dismiss('ai-file-ops');

    if (summary.applied.length > 0) {
      toast.success(
        `Applied ${summary.applied.length} change${summary.applied.length > 1 ? 's' : ''}`
      );
    }

    return summary;
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    initializeCopyCodeListeners();
  }, []);

  const handleSendMessage = async (message, isComposer = false) => {
    if (!message?.trim() || isLoading) return;

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      isComposer: isComposer
    };

    setMessages(prev => [...prev, userMessage]);
    setConversationHistory(prev => [
      ...prev,
      {
        role: 'user',
        content: message,
        timestamp: userMessage.timestamp
      }
    ]);
    if (isComposer) {
      setComposerInput('');
    } else {
      setInputMessage('');
    }
    setIsLoading(true);

    try {
      const modePayload = (agentMode || 'agent').toLowerCase();
      const shouldShowAgentStatuses = modePayload !== 'ask' || isComposer;
      const mentionPaths = extractMentionPaths(message);
      const mentionFiles = mentionPaths.length > 0 ? await loadMentionedFiles(mentionPaths) : [];

      const context = {
        current_page: 'chat',
        mode: modePayload,
        ...(isComposer && { composer_mode: true })
      };

      if (mentionFiles.length > 0) {
        context.mentioned_files = mentionFiles.map((file) => ({
          path: file.path,
          name: file.name,
          content: file.content ? file.content.substring(0, MAX_FILE_SNIPPET) : null
        }));
        context.active_file = mentionFiles[0].path;
        context.active_file_content = mentionFiles[0].content
          ? mentionFiles[0].content.substring(0, MAX_FILE_SNIPPET)
          : null;
        context.default_target_file = mentionFiles[0].path;
        context.open_files = mentionFiles.slice(0, 3).map((file, index) => ({
          path: file.path,
          name: file.name,
          content: file.content ? file.content.substring(0, MAX_FILE_SNIPPET) : null,
          language: file.path.split('.').pop() || 'plaintext',
          is_active: index === 0
        }));
      }

      if (shouldShowAgentStatuses) {
        ApiService.previewAgentStatuses(message, context)
          .then((preview) => {
            if (preview?.agent_statuses?.length) {
              scheduleAgentStatuses(preview.agent_statuses);
            }
          })
          .catch((error) => {
            console.warn('Failed to load agent status preview', error);
          });
      }

      const response = await ApiService.sendMessage(
        message,
        context,
        conversationHistory,
        { mode: modePayload }
      );

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.response,
        timestamp: response.timestamp,
        plan: response.ai_plan || null
      };

      setMessages(prev => [...prev, assistantMessage]);
      setConversationHistory(prev => [
        ...prev,
        {
          role: 'assistant',
          content: response.response,
          timestamp: response.timestamp
        }
      ]);

      if (response.file_operations?.length) {
        const summary = await applyFileOperations(response.file_operations);

        if (summary.applied.length || summary.failed.length) {
          const summaryLines = [];

          if (summary.applied.length) {
            summaryLines.push(
              `Applied ${summary.applied.length} change${summary.applied.length > 1 ? 's' : ''}:`
            );
            summary.applied.forEach((op) => {
              summaryLines.push(`- ${op.type.replace('_', ' ')} \`${op.path}\``);
            });
          }

          if (summary.failed.length) {
            summaryLines.push('');
            summaryLines.push(`Failed ${summary.failed.length} change${summary.failed.length > 1 ? 's' : ''}:`);
            summary.failed.forEach((op) => {
              summaryLines.push(`- ${op.type.replace('_', ' ')} \`${op.path}\``);
            });
          }

          const opsMessage = {
            id: Date.now() + 2,
            role: 'assistant',
            content: summaryLines.join('\n'),
            timestamp: new Date().toISOString()
          };

          setMessages(prev => [...prev, opsMessage]);
          setConversationHistory(prev => [
            ...prev,
            {
              role: 'assistant',
              content: opsMessage.content,
              timestamp: opsMessage.timestamp
            }
          ]);
        }
      }
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
      clearAgentStatuses();
    }
  };

  const handleComposerSubmit = async (e) => {
    e.preventDefault();
    await handleSendMessage(composerInput, true);
  };

  const handleChatSubmit = async (e) => {
    e.preventDefault();
    await handleSendMessage(inputMessage, false);
  };

  const clearChat = () => {
    setMessages([]);
    setConversationHistory([]);
    setInputMessage('');
    setComposerInput('');
    toast.success('Chat cleared');
  };

  const handleNewChat = () => {
    clearChat();
  };

  const quickTabs = [
    { id: 'improve', label: 'Improve system functionality and fix issues' },
    { id: 'format', label: 'Fix the chat format' },
    { id: 'enhance', label: 'Enhance UI with AI features' },
  ];
  const [activeQuickTab, setActiveQuickTab] = useState(quickTabs[0].id);

  return (
    <div className="flex flex-col h-full bg-[#050514] text-dark-100">
      <div className="px-4 py-3 border-b border-dark-800">
        <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap">
          {quickTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveQuickTab(tab.id)}
              className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
                activeQuickTab === tab.id
                  ? 'bg-dark-700 text-white'
                  : 'text-dark-300 hover:text-dark-100'
              }`}
            >
              {tab.label}
            </button>
          ))}
          <button
            onClick={handleNewChat}
            className="px-3 py-1.5 rounded-full text-sm bg-primary-600 hover:bg-primary-700 text-white transition-colors"
          >
            New Chat
          </button>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => document.getElementById('past-chat-list')?.scrollIntoView({ behavior: 'smooth' })}
              className="p-1.5 hover:bg-dark-700 rounded transition-colors"
              title="Scroll to past chats"
            >
              <Clock className="w-4 h-4 text-dark-400" />
            </button>
            <div className="relative">
              <button
                onClick={() => setShowMoreMenu(!showMoreMenu)}
                className="p-1.5 hover:bg-dark-700 rounded transition-colors"
                title="More"
              >
                <MoreVertical className="w-4 h-4 text-dark-400" />
              </button>
              {showMoreMenu && (
                <div className="absolute right-0 top-full mt-2 bg-dark-800 border border-dark-600 rounded shadow-lg z-50 min-w-[200px] py-2">
                  <button
                    type="button"
                    onClick={handleNewChat}
                    className="w-full text-left px-4 py-2 text-sm text-dark-300 hover:bg-dark-700"
                  >
                    Start fresh chat
                  </button>
                  <button
                    type="button"
                    onClick={clearChat}
                    className="w-full text-left px-4 py-2 text-sm text-dark-300 hover:bg-dark-700"
                  >
                    Clear current thread
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="border-b border-dark-800 bg-[#050514] px-4 py-4">
        <div className="max-w-4xl mx-auto w-full">
          <div className="bg-dark-800 border border-dark-700 rounded-2xl p-4 space-y-3 shadow-xl shadow-black/40">
            <div className="flex flex-wrap items-center gap-2 text-sm text-dark-300">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowAgentDropdown(!showAgentDropdown)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-dark-700 border border-dark-600 rounded-full hover:bg-dark-600 transition-colors"
                >
                  <Infinity className="w-4 h-4" />
                  <span>{agentMode.charAt(0).toUpperCase() + agentMode.slice(1)}</span>
                  <ChevronDown className="w-3 h-3" />
                </button>
                {showAgentDropdown && (
                  <div className="absolute mt-2 bg-dark-800 border border-dark-600 rounded shadow-lg z-50 min-w-[200px] py-2">
                    {['agent', 'plan', 'ask'].map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => {
                          setAgentMode(mode);
                          setShowAgentDropdown(false);
                        }}
                        className="w-full text-left px-4 py-2 text-sm text-dark-300 hover:bg-dark-700 capitalize flex items-center gap-2"
                      >
                        {mode === 'agent' ? <Infinity className="w-4 h-4" /> : <Workflow className="w-4 h-4" />}
                        {mode}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                className="flex items-center gap-1 px-3 py-1.5 bg-dark-700 border border-dark-600 rounded-full text-sm text-dark-300"
              >
                GPT-5.1 Codex High
                <ChevronDown className="w-3 h-3" />
              </button>
              <div className="flex items-center gap-1 text-xs text-dark-500 ml-auto">
                <Monitor className="w-4 h-4" />
                <span>Local</span>
              </div>
            </div>

            <form onSubmit={handleComposerSubmit} className="flex items-center gap-3">
              <input
                type="text"
                value={composerInput}
                onChange={(e) => setComposerInput(e.target.value)}
                placeholder="Plan, @ for context, / for commands"
                className="flex-1 px-4 py-3 bg-dark-900/60 border border-dark-600 rounded-xl text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                disabled={isLoading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleComposerSubmit(e);
                  }
                }}
              />
              <button
                type="submit"
                disabled={!composerInput.trim() || isLoading}
                className="p-3 rounded-xl bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="Send plan"
              >
                <Send className="w-4 h-4" />
              </button>
            </form>

            <div className="flex items-center gap-3 text-xs text-dark-400">
              <span>Press @ to link files, / for commands</span>
              <div className="flex items-center gap-2 ml-auto">
                <button
                  type="button"
                  onClick={() => setComposerInput((prev) => prev + '@')}
                  className="p-1.5 rounded hover:bg-dark-700"
                >
                  <AtSign className="w-4 h-4" />
                </button>
                <button className="p-1.5 rounded hover:bg-dark-700">
                  <Globe className="w-4 h-4" />
                </button>
                <button className="p-1.5 rounded hover:bg-dark-700">
                  <ImageIcon className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-6 bg-[#050514]">
        <div className="max-w-4xl mx-auto w-full">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center text-dark-500 text-sm">
              Start a conversation to see responses here.
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => (
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
                    className={`max-w-3xl px-4 py-3 rounded-2xl ${
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
                    {message.plan && message.role === 'assistant' && (
                      <PlanCard plan={message.plan} />
                    )}
                    <div className="text-xs opacity-70 mt-2">
                      {new Date(message.timestamp).toLocaleTimeString()}
                    </div>
                  </div>

                  {message.role === 'user' && (
                    <div className="flex-shrink-0">
                      <div className="w-8 h-8 bg-dark-700 rounded-full flex items-center justify-center">
                        <User className="w-4 h-4 text-dark-300" />
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {isLoading && (
                <div className="flex space-x-3 justify-start">
                  <div className="flex-shrink-0">
                    <div className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center">
                      <Bot className="w-4 h-4 text-white" />
                    </div>
                  </div>
                  <div className="bg-dark-800 border border-dark-700 rounded-2xl px-4 py-3">
                    <div className="flex items-center space-x-2">
                      <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
                      <span className="text-dark-300">AI is thinking...</span>
                    </div>
                    {agentStatuses.length > 0 && (
                      <div className="mt-3 space-y-1 text-xs text-dark-300">
                        {agentStatuses.map((status) => (
                          <div key={status.key} className="flex items-center gap-2">
                            <Loader2 className="w-3 h-3 animate-spin text-primary-500" />
                            <span>{status.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      <div className="px-4 py-4 border-t border-dark-800 bg-[#050514]">
        <div className="max-w-4xl mx-auto">
          <form onSubmit={handleChatSubmit} className="flex items-center gap-3 bg-dark-800 border border-dark-700 rounded-full px-4 py-2">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleChatSubmit(e);
                }
              }}
              placeholder="Continue the conversation..."
              className="flex-1 bg-transparent text-dark-100 placeholder-dark-400 focus:outline-none"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={!inputMessage.trim() || isLoading}
              className="p-2 bg-primary-600 hover:bg-primary-700 text-white rounded-full disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
          <div className="flex items-center justify-between mt-4 text-xs text-dark-400">
            <div className="flex items-center gap-2">
              <Monitor className="w-4 h-4" />
              <span>Local workspace</span>
            </div>
            <button className="text-dark-400 hover:text-dark-200 transition-colors">
              View settings
            </button>
          </div>
        </div>
      </div>

      <div id="past-chat-list" className="p-4 border-t border-dark-800 bg-dark-900">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-semibold text-dark-400 flex items-center space-x-1">
            <span>Past Chats</span>
            <ChevronDown className="w-3 h-3" />
          </h4>
          <button className="text-xs text-dark-400 hover:text-dark-300 transition-colors">
            View All
          </button>
        </div>
        <div className="space-y-1">
          {pastChats.map((chat) => (
            <div
              key={chat.id}
              className="text-xs text-dark-400 hover:text-dark-200 cursor-pointer py-1 px-2 hover:bg-dark-800 rounded transition-colors flex items-center justify-between"
            >
              <span className="truncate">{chat.title}</span>
              <span className="ml-2 text-dark-500">{chat.time}</span>
            </div>
          ))}
        </div>
      </div>

      {(showAgentDropdown || showMoreMenu) && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => {
            setShowAgentDropdown(false);
            setShowAutoDropdown(false);
            setShowMoreMenu(false);
          }}
        />
      )}
    </div>
  );
};

export default Chat;
