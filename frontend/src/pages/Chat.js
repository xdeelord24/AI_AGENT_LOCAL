import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Bot, User, Loader2,
  ChevronDown, Monitor, Infinity, Workflow,
  Globe, CheckCircle
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

const safeStringifyInput = (value, spacing = 2) => {
  const seen = new WeakSet();
  const serializer = (key, val) => {
    if (typeof val === 'bigint') {
      return val.toString();
    }
    if (typeof val === 'object' && val !== null) {
      if (seen.has(val)) {
        return '[Circular]';
      }
      seen.add(val);
    }
    if (typeof val === 'function') {
      return `[Function ${val.name || 'anonymous'}]`;
    }
    return val;
  };
  return JSON.stringify(value, serializer, spacing);
};

const normalizeMessageInput = (value) => {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeMessageInput(item))
      .filter((segment) => segment !== '')
      .join('\n\n');
  }
  if (typeof value === 'object') {
    try {
      return safeStringifyInput(value, 2);
    } catch (error) {
      return Object.prototype.toString.call(value);
    }
  }
  return String(value);
};

const Chat = () => {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [composerInput, setComposerInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationHistory, setConversationHistory] = useState([]);
  // Default to full agent behavior so follow-up chats stay in agent mode
  const [agentMode, setAgentMode] = useState('agent');
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const webSearchOptions = [
    { id: 'off', label: 'Off', description: 'AI stays within the workspace context.' },
    { id: 'browser_tab', label: 'Browser Tab', description: 'Let AI use in-app web search.' },
    { id: 'google_chrome', label: 'Google Chrome', description: 'Let AI request an external Chrome window.' }
  ];
  const [webSearchMode, setWebSearchMode] = useState('off');
  const [showWebSearchDropdown, setShowWebSearchDropdown] = useState(false);
  const [lastUserPrompt, setLastUserPrompt] = useState('');
  const [lastPromptDraft, setLastPromptDraft] = useState('');
  const [thinkingStart, setThinkingStart] = useState(null);
  const [thinkingElapsed, setThinkingElapsed] = useState(0);
  const messagesEndRef = useRef(null);
  const agentStatusTimersRef = useRef([]);

  const planStatusStyles = {
    completed: 'border-green-700 bg-green-500/10 text-green-300',
    in_progress: 'border-primary-600 bg-primary-600/10 text-primary-300',
    pending: 'border-dark-600 bg-dark-800/80 text-dark-200',
    blocked: 'border-red-700 bg-red-600/10 text-red-300'
  };

  const [agentStatuses, setAgentStatuses] = useState([]);
  const selectedWebSearchMode =
    webSearchOptions.find((mode) => mode.id === webSearchMode) || webSearchOptions[0];

  const PlanCard = ({ plan }) => {
    if (!plan) return null;

    const summary = normalizeMessageInput(
      plan.summary || plan.thoughts || plan.description || ''
    );
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
              const statusKey = String(task.status || 'pending').toLowerCase();
              const statusClass = planStatusStyles[statusKey] || planStatusStyles.pending;
              const title = normalizeMessageInput(
                task.title || task.summary || `Task ${idx + 1}`
              );
              const details =
                task.details != null ? normalizeMessageInput(task.details) : '';
              return (
                <div
                  key={task.id || `${task.title || 'task'}-${idx}`}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl bg-dark-800/70 text-sm text-dark-100"
                >
                  <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${statusClass}`}>
                    {statusKey.replace('_', ' ')}
                  </span>
                  <div className="flex-1">
                    <div className="font-medium">{title}</div>
                    {details && (
                      <div className="text-xs text-dark-300">
                        {details}
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

useEffect(() => {
  if (!thinkingStart) {
    setThinkingElapsed(0);
    return;
  }
  setThinkingElapsed(Date.now() - thinkingStart);
  const intervalId = setInterval(() => {
    setThinkingElapsed(Date.now() - thinkingStart);
  }, 1000);
  return () => clearInterval(intervalId);
}, [thinkingStart]);

  const handleSendMessage = async (message, isComposer = false) => {
    const originalMessage = message;
    const normalizedMessage = normalizeMessageInput(message);
    const safeRawContent =
      typeof originalMessage === 'string' ? originalMessage : normalizedMessage;
    if (!normalizedMessage.trim() || isLoading) return;

    const trimmedMessage = normalizedMessage.trim();
    setThinkingStart(Date.now());
    setThinkingElapsed(0);
    setLastUserPrompt(trimmedMessage);
    setLastPromptDraft(trimmedMessage);

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: normalizedMessage,
      rawContent: safeRawContent,
      timestamp: new Date().toISOString(),
      isComposer: isComposer
    };

    setMessages(prev => [...prev, userMessage]);
    setConversationHistory(prev => [
      ...prev,
      {
        role: 'user',
        content: normalizedMessage,
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
      // Treat both agent and plan as "agent-like" modes that should keep the agent behavior active
      const isAgentLikeMode = modePayload === 'agent' || modePayload === 'plan';
      const composerModeEnabled = isComposer || isAgentLikeMode;
      const shouldShowAgentStatuses = composerModeEnabled;
      const mentionPaths = extractMentionPaths(normalizedMessage);
      const mentionFiles = mentionPaths.length > 0 ? await loadMentionedFiles(mentionPaths) : [];

      const context = {
        current_page: 'chat',
        mode: modePayload,
        chat_mode: modePayload,
        web_search_mode: webSearchMode,
        ...(composerModeEnabled && { composer_mode: true })
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
        ApiService.previewAgentStatuses(normalizedMessage, context)
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
        normalizedMessage,
        context,
        conversationHistory,
        { mode: modePayload }
      );

      // Debug: inspect raw response payload from backend
      // eslint-disable-next-line no-console
      console.log('Chat.handleSendMessage: ApiService.sendMessage response', {
        response,
        responseType: typeof response,
        responseResponseType: typeof response?.response,
      });

      const assistantContent = normalizeMessageInput(response.response);

      // Debug: inspect assistant content after normalization
      // eslint-disable-next-line no-console
      console.log('Chat.handleSendMessage: assistantContent after normalizeMessageInput', {
        assistantContent,
        assistantContentType: typeof assistantContent,
      });

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: assistantContent,
        rawContent: assistantContent,
        timestamp: response.timestamp,
        plan: response.ai_plan || null
      };

      setMessages(prev => [...prev, assistantMessage]);
      setConversationHistory(prev => [
        ...prev,
        {
          role: 'assistant',
          content: assistantContent,
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
            rawContent: summaryLines.join('\n'),
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
      setThinkingStart(null);
    }
  };

  const handleResendEditedPrompt = async () => {
    if (!lastPromptDraft.trim() || isLoading) return;
    await handleSendMessage(lastPromptDraft, agentMode.toLowerCase() !== 'ask');
  };

  const handleLoadEditedPrompt = () => {
    setComposerInput(lastPromptDraft);
    const composerAnchor = document.getElementById('chat-composer');
    if (composerAnchor) {
      composerAnchor.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  const handleComposerSubmit = async (e) => {
    e.preventDefault();
    await handleSendMessage(composerInput, true);
  };

  const handleChatSubmit = async (e) => {
    e.preventDefault();
    const shouldUseComposer = agentMode.toLowerCase() !== 'ask';
    await handleSendMessage(inputMessage, shouldUseComposer);
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

  return (
    <div className="min-h-screen bg-[#04030F] text-dark-100 flex flex-col">
      <header className="border-b border-dark-800 bg-[#050514]">
        <div className="max-w-3xl mx-auto px-4 py-5 space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-dark-500">Copilot chat</p>
              <h1 className="text-2xl font-semibold text-white">Fix code modification issue</h1>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowAgentDropdown(!showAgentDropdown)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-dark-800 border border-dark-600 rounded-full text-sm text-dark-200 hover:bg-dark-700 transition-colors"
                >
                  <Infinity className="w-4 h-4" />
                  <span>{agentMode.charAt(0).toUpperCase() + agentMode.slice(1)}</span>
                  <ChevronDown className="w-3 h-3" />
                </button>
                {showAgentDropdown && (
                  <div className="absolute right-0 mt-2 bg-dark-900 border border-dark-700 rounded-xl shadow-lg z-50 min-w-[220px] py-2">
                    {['agent', 'plan', 'ask'].map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => {
                          setAgentMode(mode);
                          setShowAgentDropdown(false);
                        }}
                        className={`w-full text-left px-4 py-2 text-sm capitalize flex items-center gap-2 ${
                          agentMode === mode
                            ? 'text-white bg-primary-600/20'
                            : 'text-dark-200 hover:bg-dark-800'
                        }`}
                      >
                        {mode === 'agent' ? <Infinity className="w-4 h-4" /> : <Workflow className="w-4 h-4" />}
                        {mode}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowWebSearchDropdown((prev) => !prev)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-dark-800 border border-dark-600 rounded-full text-[11px] text-dark-300 hover:bg-dark-700 transition-colors"
                  title={`Web Search (${selectedWebSearchMode.label})`}
                >
                  <Globe className="w-4 h-4" />
                  <span className="uppercase tracking-wide">{selectedWebSearchMode.label}</span>
                  <ChevronDown className="w-3 h-3" />
                </button>
                {showWebSearchDropdown && (
                  <div className="absolute right-0 mt-2 bg-dark-900 border border-dark-700 rounded-xl shadow-lg z-50 min-w-[220px] py-2">
                    {webSearchOptions.map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => {
                          setWebSearchMode(option.id);
                          setShowWebSearchDropdown(false);
                        }}
                        className={`w-full text-left px-4 py-2 text-xs flex items-center justify-between ${
                          webSearchMode === option.id
                            ? 'text-white bg-primary-600/20'
                            : 'text-dark-200 hover:bg-dark-800'
                        }`}
                      >
                        <div className="flex flex-col">
                          <span>{option.label}</span>
                          {option.description && (
                            <span className="text-[10px] text-dark-500 mt-0.5">
                              {option.description}
                            </span>
                          )}
                        </div>
                        {webSearchMode === option.id && (
                          <CheckCircle className="w-3 h-3 text-primary-400" />
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                className="flex items-center gap-1 px-3 py-1.5 bg-dark-800 border border-dark-600 rounded-full text-xs text-dark-300"
              >
                GPT-5.1 Codex High
                <ChevronDown className="w-3 h-3" />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-dark-400">
            <span className="px-2 py-0.5 rounded-full border border-dark-700 bg-dark-900/60">
              {messages.length} message{messages.length === 1 ? '' : 's'}
            </span>
            {isLoading && (
              <span className="px-2 py-0.5 rounded-full bg-primary-600/10 text-primary-300 border border-primary-700/40">
                Thought for {Math.max(1, Math.round(thinkingElapsed / 1000))}s
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-8">
          <section className="bg-dark-800/70 border border-dark-700 rounded-2xl p-4 space-y-3 shadow-xl shadow-black/30">
            <div className="flex items-center justify-between text-xs uppercase tracking-wide text-dark-400">
              <span>Previous prompt</span>
              {lastUserPrompt && (
                <span className="text-dark-500">{lastUserPrompt.length} chars</span>
              )}
            </div>
            <textarea
              value={lastPromptDraft}
              onChange={(e) => setLastPromptDraft(e.target.value)}
              placeholder="Your last prompt will appear here after you send a message"
              rows={Math.min(8, Math.max(3, Math.ceil((lastPromptDraft.length || 40) / 80)))}
              className="w-full bg-dark-900/60 border border-dark-600 rounded-xl px-3 py-2 text-sm text-dark-100 placeholder-dark-500 focus:outline-none focus:ring-2 focus:ring-primary-600"
            />
            <div className="flex flex-wrap gap-2 text-sm">
              <button
                type="button"
                onClick={() => setLastPromptDraft(lastUserPrompt)}
                disabled={!lastUserPrompt}
                className="px-3 py-1.5 rounded-lg border border-dark-600 text-dark-200 hover:bg-dark-800 disabled:opacity-40"
              >
                Reset to original
              </button>
              <button
                type="button"
                onClick={handleLoadEditedPrompt}
                disabled={!lastPromptDraft.trim()}
                className="px-3 py-1.5 rounded-lg border border-primary-700 text-primary-300 hover:bg-primary-600/10 disabled:opacity-40"
              >
                Load into composer
              </button>
              <button
                type="button"
                onClick={handleResendEditedPrompt}
                disabled={!lastPromptDraft.trim() || isLoading}
                className="px-3 py-1.5 rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-60"
              >
                Send edited prompt
              </button>
            </div>
          </section>

          <section className="space-y-4">
            {messages.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-dark-700 bg-dark-900/40 p-6 text-center text-sm text-dark-400">
                Start a conversation to see responses here.
              </div>
            ) : (
              <>
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`rounded-2xl border ${
                      message.role === 'user'
                        ? 'border-primary-700 bg-primary-700/10'
                        : message.isError
                        ? 'border-red-800 bg-red-900/20'
                        : 'border-dark-700 bg-dark-900/60'
                    } p-4 space-y-3`}
                  >
                    {/* Debug: log each message as it is rendered in the Copilot Chat page */}
                    {(() => {
                      const normalizedContent = normalizeMessageInput(
                        message.rawContent ?? message.content
                      );
                      const formattedHtml = formatMessageContent(normalizedContent);
                      // eslint-disable-next-line no-console
                      console.log('Chat page render message bubble', {
                        id: message.id,
                        role: message.role,
                        content: message.content,
                        rawContent: message.rawContent,
                        contentType: typeof message.content,
                        rawContentType: typeof message.rawContent,
                        normalizedContent,
                        formattedHtml,
                        formattedHtmlType: typeof formattedHtml,
                      });
                      return (
                        <div
                          className="prose prose-invert max-w-none text-[15px]"
                          dangerouslySetInnerHTML={{
                            __html: formattedHtml,
                          }}
                        />
                      );
                    })()}
                    <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-dark-400">
                      {message.role === 'user' ? (
                        <>
                          <User className="w-4 h-4 text-primary-400" />
                          <span>User</span>
                        </>
                      ) : (
                        <>
                          <Bot className="w-4 h-4 text-primary-400" />
                          <span>AI Assistant</span>
                        </>
                      )}
                      <span className="text-dark-600">•</span>
                      <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
                    </div>
                    {message.plan && message.role === 'assistant' && (
                      <PlanCard plan={message.plan} />
                    )}
                  </div>
                ))}

                {isLoading && (
                  <div className="rounded-2xl border border-dark-700 bg-dark-900/60 p-4 space-y-3">
                    <div className="flex items-center gap-2 text-sm text-dark-300">
                      <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
                      <span>AI is thinking...</span>
                    </div>
                    {agentStatuses.length > 0 && (
                      <div className="grid gap-1 text-xs text-dark-300">
                        {agentStatuses.map((status) => (
                          <div
                            key={status.key}
                            className="flex items-center gap-2 rounded-lg bg-dark-800/80 px-3 py-2"
                          >
                            <Loader2 className="w-3 h-3 animate-spin text-primary-500" />
                            <span>{status.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </section>
        </div>
      </main>

      <footer className="border-t border-dark-800 bg-[#050514]" id="chat-composer">
        <div className="max-w-3xl mx-auto px-4 py-4 space-y-3">
          <form
            onSubmit={handleChatSubmit}
            className="flex items-center gap-3 bg-dark-900 border border-dark-700 rounded-2xl px-4 py-3"
          >
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
              placeholder="Write a follow-up…"
              className="flex-1 bg-transparent text-dark-100 placeholder-dark-500 focus:outline-none"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={!inputMessage.trim() || isLoading}
              className="p-3 bg-primary-600 hover:bg-primary-700 rounded-xl text-white disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
          <div className="text-xs text-dark-500 flex items-center gap-2">
            <Monitor className="w-4 h-4" />
            <span>Local workspace • Agent mode keeps editing context active</span>
          </div>
        </div>
      </footer>

      {(showAgentDropdown || showWebSearchDropdown) && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => {
            setShowAgentDropdown(false);
            setShowWebSearchDropdown(false);
          }}
        />
      )}
    </div>
  );
};

export default Chat;
