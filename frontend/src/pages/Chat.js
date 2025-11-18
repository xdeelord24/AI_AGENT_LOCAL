import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Bot, User, Loader2,
  ChevronDown, Monitor, Infinity, Workflow,
  Globe, CheckCircle
} from 'lucide-react';
import { ApiService } from '../services/api';
import { formatMessageContent, initializeCopyCodeListeners } from '../utils/messageFormatter';
import { detectNewScriptIntent } from '../utils/intentDetection';
import toast from 'react-hot-toast';

const MAX_FILE_SNIPPET = 5000;
const PLAN_PREVIEW_DELAY_MS = 350;
const MAX_PENDING_FILE_OP_PREVIEW = 6;
const MAX_FILE_CONTEXT_FILES = 5;
const MAX_AUTO_PATH_HINTS = 8;
const WORKSPACE_TREE_FETCH_DEPTH = 4;
const WORKSPACE_TREE_MAX_DEPTH = 3;
const WORKSPACE_TREE_CHILD_LIMIT = 12;

const COMMON_FILE_EXTENSIONS = new Set([
  'js',
  'jsx',
  'ts',
  'tsx',
  'py',
  'java',
  'json',
  'md',
  'mdx',
  'css',
  'scss',
  'sass',
  'less',
  'html',
  'htm',
  'yaml',
  'yml',
  'xml',
  'ini',
  'cfg',
  'conf',
  'toml',
  'lock',
  'txt',
  'env',
  'sh',
  'bash',
  'zsh',
  'bat',
  'ps1',
  'go',
  'rs',
  'rb',
  'php',
  'c',
  'h',
  'cpp',
  'hpp',
  'm',
  'mm',
  'swift',
  'kt',
  'scala',
  'cs',
  'sql',
  'prisma',
  'gradle',
  'dockerfile',
  'makefile'
]);

const SPECIAL_FILENAME_HINTS = new Set(['dockerfile', 'makefile', 'license']);

const formatDuration = (ms = 0) => {
  if (ms == null || Number.isNaN(ms)) {
    return '—';
  }
  if (ms < 1000) {
    return '<1s';
  }
  const seconds = Math.max(1, Math.round(ms / 1000));
  return `${seconds}s`;
};

const summarizePrompt = (text = '', limit = 80) => {
  const trimmed = (text || '').trim();
  if (!trimmed) {
    return '';
  }
  if (trimmed.length <= limit) {
    return trimmed;
  }
  return `${trimmed.slice(0, limit - 1)}…`;
};

const CollapsibleSection = ({
  title,
  badge,
  defaultCollapsed = false,
  children,
  accent = 'primary'
}) => {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const borderClass =
    accent === 'primary'
      ? 'border-primary-700/40 bg-dark-900/60'
      : 'border-dark-700 bg-dark-900/60';

  return (
    <div className={`rounded-2xl border ${borderClass} p-3 space-y-3`}>
      <button
        type="button"
        onClick={() => setIsCollapsed((prev) => !prev)}
        className="w-full flex items-center justify-between gap-3 text-sm text-dark-200"
      >
        <span className="font-medium">{title}</span>
        <div className="flex items-center gap-2 text-xs text-dark-400">
          {badge && (
            <span className="px-2 py-0.5 rounded-full border border-dark-600 text-[11px] uppercase tracking-wide">
              {badge}
            </span>
          )}
          <ChevronDown
            className={`w-4 h-4 transition-transform ${isCollapsed ? '' : 'rotate-180'}`}
          />
        </div>
      </button>
      {!isCollapsed && <div className="space-y-2">{children}</div>}
    </div>
  );
};

const ActivityTimeline = ({
  timeline = [],
  title = 'AI workflow activity',
  defaultCollapsed = false,
  isLive = false,
}) => {
  if (!Array.isArray(timeline) || timeline.length === 0) {
    return null;
  }

  const normalizedTimeline = timeline.map((step, idx) => {
    const activatedAt =
      step.activatedAt ??
      (step.started_at ? Date.parse(step.started_at) : Date.now());
    const durationMs =
      step.durationMs ??
      step.duration_ms ??
      (step.completedAt && activatedAt ? Math.max(0, step.completedAt - activatedAt) : 0);
    const completedAt =
      step.completedAt ??
      (durationMs && activatedAt ? activatedAt + durationMs : null);
    return {
      key: step.key || `step-${idx}`,
      label: step.label || `Step ${idx + 1}`,
      activatedAt,
      completedAt,
      durationMs: durationMs || null,
    };
  });

  const now = isLive ? Date.now() : null;

  return (
    <CollapsibleSection
      title={title}
      defaultCollapsed={defaultCollapsed}
      badge={`${normalizedTimeline.length} step${normalizedTimeline.length === 1 ? '' : 's'}`}
      accent="dark"
    >
      <ol className="space-y-2 text-sm text-dark-100">
        {normalizedTimeline.map((step, idx) => {
          const activatedAt = step.activatedAt || Date.now();
          const baselineDuration = step.durationMs ? Math.max(0, step.durationMs) : 0;
          const isRunning = isLive && !step.completedAt;
          const runningDuration = isRunning && now ? Math.max(0, now - activatedAt) : baselineDuration;
          const durationLabel = runningDuration ? formatDuration(runningDuration) : '—';
          const chipText = isRunning ? `${durationLabel} • live` : durationLabel;
          const borderClass = isRunning
            ? 'border-primary-700/60 bg-primary-900/10 text-primary-100'
            : 'border-dark-700 bg-dark-800/70 text-dark-100';

          return (
            <li
              key={`${step.key}-${idx}`}
              className={`flex items-center justify-between gap-3 rounded-xl px-3 py-2 ${borderClass}`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`px-2 py-0.5 rounded-full border text-[11px] uppercase tracking-wide ${
                    isRunning ? 'border-primary-600 text-primary-200' : 'border-dark-600 text-dark-300'
                  }`}
                >
                  {idx + 1}
                </span>
                <div className="flex flex-col">
                  <span className="font-semibold text-sm">
                    {`${durationLabel} • ${step.label}`}
                  </span>
                  {!isRunning && baselineDuration > 0 && (
                    <span className="text-[11px] text-dark-400">
                      Finished after {formatDuration(baselineDuration)}
                    </span>
                  )}
                  {isRunning && (
                    <span className="text-[11px] text-primary-200">
                      In progress — started {formatDuration(Math.max(1, runningDuration))} ago
                    </span>
                  )}
                </div>
              </div>
              <span className={`text-xs font-mono ${isRunning ? 'text-primary-200' : 'text-dark-400'}`}>
                {chipText}
              </span>
            </li>
          );
        })}
      </ol>
    </CollapsibleSection>
  );
};

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

const normalizePathCandidate = (value = '') => {
  if (!value) return '';
  let candidate = value.trim();
  if (!candidate) return '';
  candidate = candidate.replace(/^[`"'“”‘’({[]+/, '').replace(/[`"'“”‘’)}\]]+$/, '');
  candidate = candidate.replace(/[,;:?!.]+$/g, '');
  candidate = candidate.replace(/\\+/g, '/');
  if (candidate.startsWith('@')) {
    candidate = candidate.slice(1);
  }
  return candidate;
};

const extractImplicitFilePaths = (text = '') => {
  if (!text || !text.trim()) {
    return [];
  }
  const hints = new Set();

  const tryAddCandidate = (raw) => {
    if (!raw || hints.size >= MAX_AUTO_PATH_HINTS) {
      return;
    }
    const candidate = normalizePathCandidate(raw);
    if (
      !candidate ||
      candidate.length < 3 ||
      candidate.includes('://') ||
      candidate.includes('\n') ||
      /\s/.test(candidate)
    ) {
      return;
    }
    const lower = candidate.toLowerCase();
    const hasSlash = candidate.includes('/');
    const extMatch = candidate.match(/\.([a-z0-9]{1,8})$/i);
    const looksLikeFile =
      hasSlash ||
      (extMatch && COMMON_FILE_EXTENSIONS.has(extMatch[1].toLowerCase())) ||
      SPECIAL_FILENAME_HINTS.has(lower);

    if (!looksLikeFile) {
      return;
    }

    hints.add(candidate);
  };

  const slashPattern = /(?:\.{0,2}\/)?(?:[\w.-]+[\\/])+[\w.-]+(?:\.[\w.-]+)?/g;
  let match;
  while ((match = slashPattern.exec(text)) !== null && hints.size < MAX_AUTO_PATH_HINTS) {
    tryAddCandidate(match[0]);
  }

  if (hints.size < MAX_AUTO_PATH_HINTS) {
    const tokens = text.split(/[\s,;:(){}[\]<>"'`]+/);
    for (const token of tokens) {
      if (hints.size >= MAX_AUTO_PATH_HINTS) {
        break;
      }
      tryAddCandidate(token);
    }
  }

  return Array.from(hints);
};

const simplifyWorkspaceTreeNodes = (nodes = [], depth = 0) => {
  if (!Array.isArray(nodes) || depth >= WORKSPACE_TREE_MAX_DEPTH) {
    return [];
  }
  return nodes.slice(0, WORKSPACE_TREE_CHILD_LIMIT).map((node) => {
    const isDirectory = Boolean(node?.is_directory);
    const children =
      isDirectory && depth + 1 < WORKSPACE_TREE_MAX_DEPTH
        ? simplifyWorkspaceTreeNodes(node.children || [], depth + 1)
        : [];
    const hasMoreChildren =
      Boolean(node?.has_more_children) ||
      (!!node?.children && node.children.length > WORKSPACE_TREE_CHILD_LIMIT);

    return {
      name: node?.name || '',
      path: node?.path || '',
      is_directory: isDirectory,
      has_more_children: hasMoreChildren,
      children
    };
  });
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
  const [workspaceTree, setWorkspaceTree] = useState(null);
  const workspaceTreePromiseRef = useRef(null);

  const planStatusStyles = {
    completed: 'border-green-700 bg-green-500/10 text-green-300',
    in_progress: 'border-primary-600 bg-primary-600/10 text-primary-300',
    pending: 'border-dark-600 bg-dark-800/80 text-dark-200',
    blocked: 'border-red-700 bg-red-600/10 text-red-300'
  };

  const ensureWorkspaceTreeSnapshot = useCallback(async () => {
    if (Array.isArray(workspaceTree) && workspaceTree.length > 0) {
      return workspaceTree;
    }
    if (workspaceTreePromiseRef.current) {
      return workspaceTreePromiseRef.current;
    }
    const fetchPromise = ApiService.getFileTree('.', WORKSPACE_TREE_FETCH_DEPTH)
      .then((response) => {
        if (response?.tree) {
          const simplified = simplifyWorkspaceTreeNodes(response.tree.children || []);
          setWorkspaceTree(simplified);
          return simplified;
        }
        return [];
      })
      .catch((error) => {
        console.warn('Failed to load workspace tree for chat context', error);
        return [];
      })
      .finally(() => {
        workspaceTreePromiseRef.current = null;
      });
    workspaceTreePromiseRef.current = fetchPromise;
    return fetchPromise;
  }, [workspaceTree]);

  const [agentStatuses, setAgentStatuses] = useState([]);
  const [thinkingAiPlan, setThinkingAiPlan] = useState(null);
  const [pendingFileOpsQueue, setPendingFileOpsQueue] = useState([]);
  const thinkingPlanTaskCount = Array.isArray(thinkingAiPlan?.tasks)
    ? thinkingAiPlan.tasks.length
    : 0;
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

  const previewAiPlanBeforeAnswer = useCallback(async (plan) => {
    if (!plan) {
      setThinkingAiPlan(null);
      return;
    }
    setThinkingAiPlan(plan);
    await new Promise((resolve) => setTimeout(resolve, PLAN_PREVIEW_DELAY_MS));
  }, [setThinkingAiPlan]);

  const clearAgentStatuses = useCallback(() => {
    setAgentStatuses([]);
  }, []);

  const showThinkingStatus = useCallback((label) => {
    if (!label) {
      clearAgentStatuses();
      return;
    }
    const now = Date.now();
    setAgentStatuses([{
      key: `thinking-${now}`,
      label,
      activatedAt: now,
      completedAt: null,
      durationMs: null,
    }]);
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

  const appendFileOpsSummaryMessage = useCallback(
    (summary) => {
      const appliedCount = summary?.applied?.length || 0;
      const failedCount = summary?.failed?.length || 0;

      if (!appliedCount && !failedCount) {
        return;
      }

      const summaryLines = [];

      if (appliedCount) {
        summaryLines.push(
          `Applied ${appliedCount} change${appliedCount > 1 ? 's' : ''}:`
        );
        summary.applied.forEach((op) => {
          summaryLines.push(`- ${op.type.replace('_', ' ')} \`${op.path}\``);
        });
      }

      if (failedCount) {
        if (summaryLines.length) {
          summaryLines.push('');
        }
        summaryLines.push(
          `Failed ${failedCount} change${failedCount > 1 ? 's' : ''}:`
        );
        summary.failed.forEach((op) => {
          summaryLines.push(`- ${op.type.replace('_', ' ')} \`${op.path}\``);
        });
      }

      const content = summaryLines.join('\n');
      const opsMessage = {
        id: Date.now() + 2,
        role: 'assistant',
        content,
        rawContent: content,
        timestamp: new Date().toISOString()
      };

      setMessages((prev) => [...prev, opsMessage]);
      setConversationHistory((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: opsMessage.content,
          timestamp: opsMessage.timestamp
        }
      ]);
    },
    [setMessages, setConversationHistory]
  );

  const handleApplyPendingFileOps = useCallback(
    async (entry) => {
      if (!entry?.operations?.length) {
        toast.error('No file changes to apply.');
        setPendingFileOpsQueue((prev) => prev.filter((item) => item.id !== entry?.id));
        return;
      }

      const summary = await applyFileOperations(entry.operations);
      appendFileOpsSummaryMessage(summary);
      setPendingFileOpsQueue((prev) => prev.filter((item) => item.id !== entry.id));
    },
    [applyFileOperations, appendFileOpsSummaryMessage, setPendingFileOpsQueue]
  );

  const handleDeclinePendingFileOps = useCallback(
    (entryId) => {
      setPendingFileOpsQueue((prev) => prev.filter((item) => item.id !== entryId));
      toast('AI file changes discarded.');
    },
    [setPendingFileOpsQueue]
  );

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
    ensureWorkspaceTreeSnapshot();
  }, [ensureWorkspaceTreeSnapshot]);

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
    const modePayload = (agentMode || 'agent').toLowerCase();
    const isAgentLikeMode = modePayload === 'agent' || modePayload === 'plan';
    const composerModeEnabled = isComposer || isAgentLikeMode;
    const shouldShowAgentStatuses = composerModeEnabled;
    const triggerPhase = (key, label) => {
      if (!shouldShowAgentStatuses) {
        return;
      }
      if (key === 'thinking') {
        showThinkingStatus(label);
      }
    };

    clearAgentStatuses();
    const initialLabel = trimmedMessage
      ? `Thinking about: ${summarizePrompt(trimmedMessage, 90)}`
      : 'Thinking about the new request…';
    triggerPhase('thinking', initialLabel);
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
    setThinkingAiPlan(null);
    setIsLoading(true);
  
    try {
      triggerPhase('analysis', 'Analyzing context and recent history');
      const mentionPaths = extractMentionPaths(normalizedMessage);
      const implicitPaths =
        mentionPaths.length === 0 ? extractImplicitFilePaths(normalizedMessage) : [];
      const combinedPaths = Array.from(new Set([...mentionPaths, ...implicitPaths])).slice(
        0,
        MAX_FILE_CONTEXT_FILES
      );
      const mentionFiles =
        combinedPaths.length > 0 ? await loadMentionedFiles(combinedPaths) : [];
      triggerPhase('grepping', 'Grepping workspace for references');
      const isNewScriptRequest = detectNewScriptIntent(trimmedMessage);

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

      if (isNewScriptRequest) {
        context.intent = 'new_script';
        context.requested_new_script = true;
        context.disable_active_file_context = true;
        if (!mentionFiles.length) {
          delete context.active_file;
          delete context.active_file_content;
          delete context.default_target_file;
          context.open_files = [];
        }
      }

      if (mentionFiles.length === 0 || mentionPaths.length === 0) {
        const workspaceSnapshot = await ensureWorkspaceTreeSnapshot();
        if (workspaceSnapshot?.length) {
          context.file_tree_structure = workspaceSnapshot;
        }
      }
      triggerPhase('collecting', 'Collecting workspace structure, open files, and directory info');
      triggerPhase('subtasks', 'Breaking work into actionable subtasks');
      triggerPhase('sequencing', 'Sequencing tasks for execution');
      triggerPhase('drafting', 'Drafting potential code changes');

      const response = await ApiService.sendMessage(
        normalizedMessage,
        context,
        conversationHistory,
        { mode: modePayload }
      );
      triggerPhase('monitoring', 'Monitoring TODO progress and updating task statuses');

      const assistantPlan = response.ai_plan || null;
      await previewAiPlanBeforeAnswer(assistantPlan);

      const assistantContent = normalizeMessageInput(response.response);

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: assistantContent,
        rawContent: assistantContent,
        timestamp: response.timestamp,
        plan: assistantPlan,
        ...(Array.isArray(response.activity_log) && response.activity_log.length
          ? { activityLog: response.activity_log }
          : {})
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
        const pendingEntry = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          operations: response.file_operations,
          receivedAt: new Date().toISOString(),
          sourceMessageId: assistantMessage.id
        };
        setPendingFileOpsQueue((prev) => [...prev, pendingEntry]);
        toast.success('Review the pending AI file changes before applying them.');
      }
      triggerPhase('verifying', 'Verifying updates and running quick checks');
      triggerPhase('reporting', 'Reporting outcomes and next steps');
      setIsLoading(false);
      setThinkingAiPlan(null);
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
      setIsLoading(false);
      setThinkingAiPlan(null);
    } finally {
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
    setPendingFileOpsQueue([]);
    clearAgentStatuses();
    setThinkingAiPlan(null);
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

          {pendingFileOpsQueue.length > 0 && (
            <section className="bg-dark-800/70 border border-primary-700/40 rounded-2xl p-4 space-y-3 shadow-xl shadow-primary-900/20">
              <div className="flex items-center justify-between text-xs uppercase tracking-wide text-primary-200">
                <span>Pending AI file changes</span>
                <span>
                  {pendingFileOpsQueue.length} package{pendingFileOpsQueue.length === 1 ? '' : 's'}
                </span>
              </div>
              {pendingFileOpsQueue.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded-xl border border-dark-700 bg-dark-900/60 p-3 space-y-3"
                >
                  <div className="text-sm text-dark-100">
                    {entry.operations.length} proposed change
                    {entry.operations.length === 1 ? '' : 's'} awaiting approval
                  </div>
                  <ul className="space-y-1 text-xs text-dark-300">
                    {entry.operations.slice(0, MAX_PENDING_FILE_OP_PREVIEW).map((op, idx) => (
                      <li key={`${entry.id}-${idx}`} className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded-full border border-dark-600 text-[10px] uppercase tracking-wide text-primary-200">
                          {String(op.type || 'edit_file').replace('_', ' ')}
                        </span>
                        <code className="text-dark-100">{op.path || 'workspace'}</code>
                      </li>
                    ))}
                  </ul>
                  {entry.operations.length > MAX_PENDING_FILE_OP_PREVIEW && (
                    <div className="text-xs text-dark-500">
                      +{entry.operations.length - MAX_PENDING_FILE_OP_PREVIEW} more change
                      {entry.operations.length - MAX_PENDING_FILE_OP_PREVIEW === 1 ? '' : 's'}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => handleApplyPendingFileOps(entry)}
                      className="px-3 py-1.5 rounded-lg bg-primary-600 text-white hover:bg-primary-700"
                    >
                      Apply changes
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeclinePendingFileOps(entry.id)}
                      className="px-3 py-1.5 rounded-lg border border-dark-600 text-dark-200 hover:bg-dark-800"
                    >
                      Decline
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          <section className="space-y-4">
            {messages.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-dark-700 bg-dark-900/40 p-6 text-center text-sm text-dark-400">
                Start a conversation to see responses here.
              </div>
            ) : (
              <>
                {messages.map((message) => {
                  const pendingOpsForMessage = pendingFileOpsQueue.find(
                    (entry) => entry.sourceMessageId === message.id
                  );
                  return (
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
                      {(() => {
                        const normalizedContent = normalizeMessageInput(
                          message.rawContent ?? message.content
                        );
                        const formattedHtml = formatMessageContent(normalizedContent);
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
                      {pendingOpsForMessage && message.role === 'assistant' && (
                        <div className="text-xs text-primary-200 bg-primary-900/20 border border-primary-800/40 rounded-xl px-3 py-2">
                          AI prepared {pendingOpsForMessage.operations.length} change
                          {pendingOpsForMessage.operations.length === 1 ? '' : 's'}.
                          Review them in the “Pending AI file changes” panel before applying.
                        </div>
                      )}
                      {message.plan && message.role === 'assistant' && (
                        <PlanCard plan={message.plan} />
                      )}
                      {message.activityLog?.length > 0 && message.role === 'assistant' && (
                        <ActivityTimeline
                          timeline={message.activityLog}
                          title="AI workflow (recorded)"
                          defaultCollapsed
                        />
                      )}
                    </div>
                  );
                })}

                {isLoading && (
                  <div className="rounded-2xl border border-dark-700 bg-dark-900/60 p-4 space-y-4">
                    <div className="flex items-center gap-2 text-sm text-dark-300">
                      <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
                      <span>
                        AI is thinking… {Math.max(1, Math.round(thinkingElapsed / 1000))}s elapsed
                      </span>
                    </div>
                    {thinkingAiPlan && (
                      <CollapsibleSection
                        title="TODO plan before execution"
                        defaultCollapsed={false}
                        badge={`${thinkingPlanTaskCount} task${thinkingPlanTaskCount === 1 ? '' : 's'}`}
                      >
                        <PlanCard plan={thinkingAiPlan} />
                      </CollapsibleSection>
                    )}
                    <ActivityTimeline
                      timeline={agentStatuses}
                      isLive
                      defaultCollapsed={false}
                      title="AI workflow (live)"
                    />
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
