import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { 
  X, ChevronLeft, ChevronRight, Maximize2,
  Code2, Bot, Wifi, WifiOff,
  Folder, File, FilePlus, FolderPlus,
  ChevronRight as ChevronRightIcon, ChevronDown,
  Send, User, Loader2, CheckCircle, AlertCircle,
  Infinity, AtSign, Globe, Image, Mic, Square, Plus, Clock, History, MoreVertical,
  RefreshCw, Minimize2, Workflow, Trash2, GitCompare, Clipboard, Copy, Scissors,
  Terminal, Share2, ExternalLink, FileSearch, Link as LinkIcon, Play, Bug, BarChart2,
  Edit2
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { ApiService } from '../services/api';
import { formatMessageContent, initializeCopyCodeListeners } from '../utils/messageFormatter';
import { detectNewScriptIntent } from '../utils/intentDetection';
import toast from 'react-hot-toast';

const createUniqueLineId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const normalizeTreeNode = (node) => {
  if (!node) return null;
  const normalizedPath = node.path ? node.path.replace(/\\/g, '/') : '.';
  return {
    ...node,
    path: normalizedPath,
    children: node.children ? node.children.map((child) => normalizeTreeNode(child)) : []
  };
};

const flattenTreeNodes = (nodes = [], accumulator = []) => {
  nodes.forEach((node) => {
    accumulator.push(node);
    if (node.children && node.children.length > 0) {
      flattenTreeNodes(node.children, accumulator);
    }
  });
  return accumulator;
};

const normalizeEditorPath = (path = '') => {
  if (!path) return '';
  return path.replace(/\\/g, '/');
};

// Ensure we only keep the final operation per file path so we don't
// duplicate work or notifications when the agent emits multiple ops
// for the same file (common with auto-continue/new-script flows).
const coalesceFileOperationsForEditor = (operations = []) => {
  if (!Array.isArray(operations) || operations.length === 0) {
    return [];
  }

  const seenPaths = new Set();
  const resultReversed = [];

  for (let i = operations.length - 1; i >= 0; i -= 1) {
    const op = operations[i];
    const rawPath = op?.path;
    const normalizedPath = normalizeEditorPath(rawPath || '');
    if (!normalizedPath) {
      continue;
    }
    if (seenPaths.has(normalizedPath)) {
      continue;
    }
    seenPaths.add(normalizedPath);
    resultReversed.push({
      ...op,
      path: normalizedPath,
    });
  }

  return resultReversed.reverse();
};

const MAX_TERMINAL_HISTORY = 500;
const TERMINAL_HISTORY_STORAGE_KEY = 'terminalHistory';
const COMPLETION_LIST_COLUMNS = 4;
const QUICK_TERMINAL_COMMANDS = ['ls', 'dir', 'pwd'];
const PLAN_PREVIEW_DELAY_MS = 350;
const MAX_FILE_SUGGESTIONS = 10;

// Simple line-based diff to power inline change previews for file operations
const computeLineDiff = (beforeContent = '', afterContent = '', options = {}) => {
  const maxLines = options.maxLines ?? 220;
  const beforeLines = (beforeContent || '').split('\n').slice(0, maxLines);
  const afterLines = (afterContent || '').split('\n').slice(0, maxLines);

  const m = beforeLines.length;
  const n = afterLines.length;

  // Dynamic programming table for longest common subsequence
  const dp = Array(m + 1)
    .fill(null)
    .map(() => Array(n + 1).fill(0));

  for (let i = 1; i <= m; i += 1) {
    for (let j = 1; j <= n; j += 1) {
      if (beforeLines[i - 1] === afterLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to build diff
  const result = [];
  let i = m;
  let j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && beforeLines[i - 1] === afterLines[j - 1]) {
      result.push({
        type: 'context',
        oldNumber: i,
        newNumber: j,
        text: beforeLines[i - 1],
      });
      i -= 1;
      j -= 1;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.push({
        type: 'added',
        oldNumber: null,
        newNumber: j,
        text: afterLines[j - 1],
      });
      j -= 1;
    } else if (i > 0) {
      result.push({
        type: 'removed',
        oldNumber: i,
        newNumber: null,
        text: beforeLines[i - 1],
      });
      i -= 1;
    } else {
      break;
    }
  }

  result.reverse();

  // If the diff is extremely long, trim the middle to keep previews readable
  const maxDiffLines = options.maxDiffLines ?? 260;
  if (result.length > maxDiffLines) {
    const head = result.slice(0, Math.floor(maxDiffLines / 2));
    const tail = result.slice(result.length - Math.floor(maxDiffLines / 2));
    return [...head, { type: 'skip', text: `… ${result.length - maxDiffLines} more changed lines …` }, ...tail];
  }

  return result;
};

const generateTerminalSessionId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `terminal-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

const normalizeChatInput = (value) => {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeChatInput(item))
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

const MenuDropdown = ({ label, items }) => (
  <div className="relative group">
    <button type="button" className="hover:bg-dark-700 px-2 py-1 rounded text-sm text-dark-200">
      {label}
    </button>
    <div className="hidden group-hover:block absolute top-full left-0 mt-1 bg-dark-800 border border-dark-700 rounded shadow-lg z-50 min-w-[220px]">
      {items.map((item, index) => {
        if (item.type === 'separator') {
          return <div key={`${label}-sep-${index}`} className="h-px bg-dark-700 my-1" />;
        }
        return (
          <button
            key={`${label}-${item.label}-${index}`}
            onClick={(e) => {
              e.preventDefault();
              if (item.disabled) return;
              item.onSelect?.();
            }}
            disabled={item.disabled}
            className={`w-full text-left px-4 py-2 text-sm ${
              item.disabled
                ? 'text-dark-600 cursor-not-allowed'
                : 'text-dark-200 hover:bg-dark-700'
            }`}
          >
            <div className="flex items-center justify-between space-x-4">
              <span>{item.label}</span>
              {item.shortcut && (
                <span className="text-xs text-dark-500">{item.shortcut}</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  </div>
);

const IDELayout = ({ isConnected, currentModel, availableModels, onModelSelect }) => {
  // Panel visibility states
  const [leftSidebarVisible, setLeftSidebarVisible] = useState(true);
  const [rightSidebarVisible, setRightSidebarVisible] = useState(true);
  const [bottomPanelVisible, setBottomPanelVisible] = useState(true);
  const [bottomPanelTab, setBottomPanelTab] = useState('terminal');
  
  // Panel size states
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(256); // 64 * 4 = 256px (w-64)
  const [rightSidebarWidth, setRightSidebarWidth] = useState(320); // 80 * 4 = 320px (w-80)
  const [bottomPanelHeight, setBottomPanelHeight] = useState(256); // 64 * 4 = 256px (h-64)
  
  // Resize states
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);
  const [isResizingBottom, setIsResizingBottom] = useState(false);
  
  // File explorer states
  const [fileTree, setFileTree] = useState([]);
  const [projectRoot, setProjectRoot] = useState({ name: 'Workspace', path: '.' });
  const [currentPath, setCurrentPath] = useState('.');
  const [selectedFile, setSelectedFile] = useState(null);
  const [expandedFolders, setExpandedFolders] = useState(new Set());
  const [isFileTreeLoading, setIsFileTreeLoading] = useState(false);
  const [fileContextMenu, setFileContextMenu] = useState({ visible: false, x: 0, y: 0, target: null });
  const [fileClipboard, setFileClipboard] = useState(null);
  const [compareSource, setCompareSource] = useState(null);
  const [comparisonState, setComparisonState] = useState(null);
  const [folderSearchResults, setFolderSearchResults] = useState(null);
  const isWindowsPlatform = typeof navigator !== 'undefined' && /win/i.test(navigator.userAgent || '');

  const closeFileContextMenu = useCallback(() => {
    setFileContextMenu({ visible: false, x: 0, y: 0, target: null });
  }, []);

  // Editor states
  const [editorContent, setEditorContent] = useState('');
  const [editorLanguage, setEditorLanguage] = useState('python');
  const [openFiles, setOpenFiles] = useState([]);
  const [activeTab, setActiveTab] = useState(null);
  const [editorOptions, setEditorOptions] = useState({
    fontSize: 14,
    fontFamily: 'JetBrains Mono, Fira Code, Monaco, Consolas, monospace',
    minimap: { enabled: true },
    wordWrap: 'on',
    lineNumbers: 'on',
    automaticLayout: true,
    glyphMargin: true,
  });
  const [isEditorReady, setIsEditorReady] = useState(false);
  
  // Chat states
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [composerInput, setComposerInput] = useState('');
  const [followUpInput, setFollowUpInput] = useState('');
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [chatAbortController, setChatAbortController] = useState(null);
  const [chatTabs, setChatTabs] = useState([{ id: 1, title: 'New Chat', isActive: true }]);
  const [activeChatTab, setActiveChatTab] = useState(1);
  const chatModeOptions = [
    { id: 'ask', label: 'Ask', description: 'Get a single, direct answer.' },
    { id: 'plan', label: 'Plan', description: 'Have the AI outline steps before acting.' },
    { id: 'agent', label: 'Agent', description: 'Let the AI act like a coding copilot.' }
  ];
  const webSearchOptions = [
    { id: 'off', label: 'Off', description: 'AI stays within the workspace context.' },
    { id: 'browser_tab', label: 'Browser Tab', description: 'Let AI open the in-app browser tab.' },
    { id: 'google_chrome', label: 'Google Chrome', description: 'Let AI request an external Chrome window.' }
  ];
  // Default to full agent behavior so follow-up chats stay in agent mode
  const [agentMode, setAgentMode] = useState('agent');
  const [webSearchMode, setWebSearchMode] = useState('off');
  const [showWebSearchMenu, setShowWebSearchMenu] = useState(false);
  const [showFileSuggestions, setShowFileSuggestions] = useState(false);
  const [fileSuggestions, setFileSuggestions] = useState([]);
  const [mentionPosition, setMentionPosition] = useState(null);
  const [suggestionInputType, setSuggestionInputType] = useState(null); // 'composer' or 'chat'
  const [pendingFileOperations, setPendingFileOperations] = useState(null);
  const [activeFileOperationIndex, setActiveFileOperationIndex] = useState(0);
  const [isApplyingFileOperations, setIsApplyingFileOperations] = useState(false);
  const [chatStatus, setChatStatus] = useState(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState(false);
  const [showConnectivityPanel, setShowConnectivityPanel] = useState(false);
  const [thinkingAiPlan, setThinkingAiPlan] = useState(null);
  const [connectivitySettings, setConnectivitySettings] = useState(null);
  const [isConnectivityLoading, setIsConnectivityLoading] = useState(false);
  const [isConnectivitySaving, setIsConnectivitySaving] = useState(false);
  const [isTestingConnectivity, setIsTestingConnectivity] = useState(false);
  const [ollamaModels, setOllamaModels] = useState([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [showAutoDropdown, setShowAutoDropdown] = useState(false);
  const [showAgentModeMenu, setShowAgentModeMenu] = useState(false);
  const [agentStatuses, setAgentStatuses] = useState([]);
  const composerInputRef = useRef(null);
  const chatInputRef = useRef(null);
  const editorRef = useRef(null);
  const searchInputRef = useRef(null);
  const terminalOutputRef = useRef(null);
  const terminalInputRef = useRef(null);
  const completionRequestIdRef = useRef(0);
  const historyDraftRef = useRef('');
  const agentStatusTimersRef = useRef([]);
  const agentModeMenuRef = useRef(null);
  const webSearchMenuRef = useRef(null);
  const monacoRef = useRef(null);
  const editorDiffDecorationsRef = useRef([]);
  const selectedChatMode = chatModeOptions.find(mode => mode.id === agentMode) || chatModeOptions[0];
  const selectedWebSearchMode = webSearchOptions.find(mode => mode.id === webSearchMode) || webSearchOptions[0];

  useEffect(() => {
    initializeCopyCodeListeners();
  }, []);

  const buildFileOperationPreviews = useCallback(
    async (operations = []) => {
      const enhanced = [];

      for (const op of operations) {
        const opType = (op.type || '').toLowerCase();
        const targetPath = op.path;

        let beforeContent = '';
        let afterContent = '';

        try {
          if (opType === 'create_file') {
            beforeContent = '';
            afterContent = op.content || '';
          } else if (opType === 'edit_file') {
            // Prefer current in-memory content if the file is already open
            const openMatch = openFiles.find((f) => f.path === targetPath);
            if (openMatch && typeof openMatch.content === 'string') {
              beforeContent = openMatch.content;
            } else {
              const existing = await ApiService.readFile(targetPath);
              beforeContent = existing?.content || '';
            }
            afterContent = op.content || '';
          } else if (opType === 'delete_file') {
            const openMatch = openFiles.find((f) => f.path === targetPath);
            if (openMatch && typeof openMatch.content === 'string') {
              beforeContent = openMatch.content;
            } else {
              const existing = await ApiService.readFile(targetPath);
              beforeContent = existing?.content || '';
            }
            afterContent = '';
          } else {
            afterContent = op.content || '';
          }
        } catch (error) {
          // If we fail to load the original content, fall back to whatever we have
          // eslint-disable-next-line no-console
          console.warn('buildFileOperationPreviews: failed to load original content for', targetPath, error);
          if (!beforeContent) {
            const openMatch = openFiles.find((f) => f.path === targetPath);
            beforeContent = openMatch?.content || '';
          }
        }

        const diff = computeLineDiff(beforeContent, afterContent);

        enhanced.push({
          ...op,
          beforeContent,
          afterContent,
          diff,
        });
      }

      return enhanced;
    },
    [openFiles]
  );

  const focusSearchInput = useCallback(() => {
    if (searchInputRef.current) {
      searchInputRef.current.focus();
      searchInputRef.current.select();
    }
  }, []);

  const formatDisplayPath = useCallback((path) => {
    if (!path) return '';
    const normalized = path.replace(/\\/g, '/');
    if (normalized.startsWith('./')) {
      return normalized.slice(2);
    }
    if (projectRoot.path && projectRoot.path !== '.' && normalized.startsWith(`${projectRoot.path}/`)) {
      return normalized.slice(projectRoot.path.length + 1);
    }
    return normalized;
  }, [projectRoot.path]);

  const handleConnectivityChange = (field, value) => {
    setConnectivitySettings(prev => ({
      ...(prev || {}),
      [field]: value
    }));
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

  useEffect(() => {
    if (!showAgentModeMenu) return;
    const handleClickOutside = (event) => {
      if (agentModeMenuRef.current && !agentModeMenuRef.current.contains(event.target)) {
        setShowAgentModeMenu(false);
      }
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowAgentModeMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showAgentModeMenu]);

  useEffect(() => {
    if (!showWebSearchMenu) return;
    const handleClickOutside = (event) => {
      if (webSearchMenuRef.current && !webSearchMenuRef.current.contains(event.target)) {
        setShowWebSearchMenu(false);
      }
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowWebSearchMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showWebSearchMenu]);

  const handleSaveConnectivity = async () => {
    if (!connectivitySettings) return;
    setIsConnectivitySaving(true);
    try {
      await ApiService.updateSettings({
        ollama_url: connectivitySettings.ollamaUrl,
        ollama_direct_url: connectivitySettings.ollamaDirectUrl,
        use_proxy: connectivitySettings.useProxy,
        default_model: connectivitySettings.currentModel
      });
      // Also select the model if it changed
      if (connectivitySettings.currentModel) {
        try {
          await ApiService.selectModel(connectivitySettings.currentModel);
        } catch (error) {
          console.error('Failed to select model:', error);
        }
      }
      toast.success('Connectivity settings saved');
      await loadConnectivitySettings();
      await loadAvailableModels(); // Refresh models after saving
      await ApiService.testOllamaConnection();
      const status = await ApiService.getChatStatus();
      setChatStatus(status);
      // Notify parent component about model change
      if (onModelSelect && connectivitySettings.currentModel) {
        onModelSelect(connectivitySettings.currentModel);
      }
    } catch (error) {
      console.error('Failed to save connectivity settings:', error);
      toast.error(error.response?.data?.detail || 'Failed to save connectivity settings');
    } finally {
      setIsConnectivitySaving(false);
    }
  };

  const handleTestConnectivity = async () => {
    setIsTestingConnectivity(true);
    try {
      const response = await ApiService.testOllamaConnection();
      const isConnected = !!response?.connected;
      const statusMessage =
        response?.message ||
        (isConnected ? 'Ollama connection successful' : 'Ollama connection failed');

      if (isConnected) {
        toast.success(statusMessage);
        if (Array.isArray(response?.available_models) && response.available_models.length > 0) {
          setOllamaModels(response.available_models);
        } else {
          await loadAvailableModels();
        }
      } else {
        toast.error(statusMessage);
      }

      try {
        const status = await ApiService.getChatStatus();
        setChatStatus(status);
      } catch (statusError) {
        console.warn('Failed to refresh chat status after connectivity test', statusError);
      }
    } catch (error) {
      console.error('Failed to test connectivity:', error);
      const detail =
        error?.response?.data?.detail ||
        error?.message ||
        'Failed to test Ollama connection';
      const message = detail.includes('Failed to test')
        ? detail
        : `Failed to test Ollama connection: ${detail}`;
      toast.error(message);
    } finally {
      setIsTestingConnectivity(false);
    }
  };

  const handleSelectModel = async (modelName) => {
    try {
      await ApiService.selectModel(modelName);
      setShowAutoDropdown(false);
      
      // Notify parent component about model change
      if (onModelSelect) {
        onModelSelect(modelName);
      }
      
      // Update chat status to reflect new model
      const status = await ApiService.getChatStatus();
      setChatStatus(status);
      
      toast.success(`Selected model: ${modelName}`);
    } catch (error) {
      console.error('Failed to select model:', error);
      toast.error(`Failed to select model: ${error.response?.data?.detail || error.message}`);
    }
  };
  const pastChats = [
    { id: 1, title: 'Show available AI models in settings', time: 'Now' },
    { id: 2, title: 'Fix copy code function issue', time: '7m' },
    { id: 3, title: 'Improve system functionality and fix issues', time: '25m' }
  ];
  
  const [showPastChats, setShowPastChats] = useState(true);
  
  // File/Folder picker states
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [pickerPath, setPickerPath] = useState('.');
  const [pickerTree, setPickerTree] = useState([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSelectedPath, setPickerSelectedPath] = useState('');
  const [pickerMode, setPickerMode] = useState('folder'); // 'folder' or 'file'
  
  // Terminal states
  const [terminalSessionId, setTerminalSessionId] = useState(() => {
    if (typeof window !== 'undefined') {
      const storedId = window.localStorage.getItem('terminalSessionId');
      if (storedId) {
        return storedId;
      }
    }
    return generateTerminalSessionId();
  });
  const [terminalCwd, setTerminalCwd] = useState('.');
  const [terminalOutput, setTerminalOutput] = useState([]);
  const [terminalInput, setTerminalInput] = useState('');
  const [isTerminalBusy, setIsTerminalBusy] = useState(false);
  const [isStoppingTerminal, setIsStoppingTerminal] = useState(false);
  const [terminalHistory, setTerminalHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(null);
  const [showHistoryPanel, setShowHistoryPanel] = useState(false);
  const [historyFilter, setHistoryFilter] = useState('');
  const [isCompletingTerminal, setIsCompletingTerminal] = useState(false);
  const filteredHistory = useMemo(() => {
    if (!historyFilter) {
      return terminalHistory;
    }
    const lowered = historyFilter.toLowerCase();
    return terminalHistory.filter((entry) => entry.toLowerCase().includes(lowered));
  }, [terminalHistory, historyFilter]);

  const recentHistoryEntries = useMemo(() => {
    return filteredHistory.slice(-50).reverse();
  }, [filteredHistory]);

  const flattenedFileNodes = useMemo(() => {
    if (!Array.isArray(fileTree) || fileTree.length === 0) {
      return [];
    }
    return flattenTreeNodes(fileTree).filter((node) => !node.is_directory);
  }, [fileTree]);

  const loadProjectTree = useCallback(async (path = '.', options = {}) => {
    const { setAsRoot = true, showToastMessage = false, maxDepth = 8 } = options;
    try {
      setIsFileTreeLoading(true);
      const response = await ApiService.getFileTree(path, maxDepth);
      if (!response?.tree) {
        throw new Error('Invalid tree response');
      }
      const normalizedTree = normalizeTreeNode(response.tree);
      if (!normalizedTree) {
        throw new Error('Unable to normalize tree');
      }
      setProjectRoot({
        name: normalizedTree.name || 'Workspace',
        path: normalizedTree.path || '.'
      });
      setFileTree(normalizedTree.children || []);
      if (setAsRoot) {
        setCurrentPath(normalizedTree.path || '.');
      }
      setExpandedFolders(new Set());
      if (showToastMessage) {
        toast.success(`Opened ${normalizedTree.name}`);
      }
    } catch (error) {
      console.error('Error loading directory:', error);
      toast.error(error.response?.data?.detail || 'Failed to load directory');
      setFileTree([]);
    } finally {
      setIsFileTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProjectTree('.', { setAsRoot: true, showToastMessage: false });
  }, [loadProjectTree]);

  useEffect(() => {
    const fetchStatus = async () => {
      setIsLoadingStatus(true);
      try {
        const status = await ApiService.getChatStatus();
        setChatStatus(status);
      } catch (error) {
        console.error('Failed to fetch chat status:', error);
      } finally {
        setIsLoadingStatus(false);
      }
    };
    fetchStatus();
  }, []);

  const loadAvailableModels = useCallback(async () => {
    setIsLoadingModels(true);
    try {
      const response = await ApiService.getModels();
      setOllamaModels(response.models || []);
    } catch (error) {
      console.error('Failed to load available models:', error);
      // Don't show error toast, just log it
    } finally {
      setIsLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    // Load available models on mount
    loadAvailableModels();
  }, [loadAvailableModels]);

  const loadConnectivitySettings = useCallback(async () => {
    setIsConnectivityLoading(true);
    try {
      const response = await ApiService.getSettings();
      setConnectivitySettings({
        ollamaUrl: response.ollama_url || 'http://localhost:5000',
        ollamaDirectUrl: response.ollama_direct_url || 'http://localhost:11434',
        useProxy: response.use_proxy ?? true,
        currentModel: response.current_model || response.default_model || 'codellama',
      });
      // Also fetch available models
      await loadAvailableModels();
    } catch (error) {
      console.error('Failed to load connectivity settings:', error);
      toast.error('Could not load connectivity settings');
    } finally {
      setIsConnectivityLoading(false);
    }
  }, [loadAvailableModels]);

  const refreshFileTree = useCallback(async () => {
    await loadProjectTree(currentPath || '.', { setAsRoot: true, showToastMessage: false });
  }, [currentPath, loadProjectTree]);

  const handleCollapseExplorer = useCallback(() => {
    setExpandedFolders(new Set());
  }, []);

  const handleRefreshExplorer = useCallback(async () => {
    await refreshFileTree();
  }, [refreshFileTree]);

  useEffect(() => {
    if (!activeTab) {
      editorRef.current = null;
      setIsEditorReady(false);
    }
  }, [activeTab]);

  useEffect(() => {
    const ensureSession = async () => {
      try {
        const response = await ApiService.ensureTerminalSession(terminalSessionId);
        if (response?.session_id && response.session_id !== terminalSessionId) {
          setTerminalSessionId(response.session_id);
        }
        if (response?.cwd) {
          setTerminalCwd(response.cwd);
        }
        if (typeof window !== 'undefined' && response?.session_id) {
          window.localStorage.setItem('terminalSessionId', response.session_id);
        }
      } catch (error) {
        console.error('Error initializing terminal session:', error);
        toast.error('Failed to initialize terminal session');
      }
    };
    ensureSession();
  }, [terminalSessionId]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      const storedHistory = window.localStorage.getItem(TERMINAL_HISTORY_STORAGE_KEY);
      if (storedHistory) {
        const parsed = JSON.parse(storedHistory);
        if (Array.isArray(parsed)) {
          setTerminalHistory(parsed.slice(-MAX_TERMINAL_HISTORY));
        }
      }
    } catch (error) {
      console.error('Error loading terminal history:', error);
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(
        TERMINAL_HISTORY_STORAGE_KEY,
        JSON.stringify(terminalHistory.slice(-MAX_TERMINAL_HISTORY))
      );
    } catch (error) {
      console.error('Error saving terminal history:', error);
    }
  }, [terminalHistory]);
  
  const getLanguageFromPath = useCallback((path) => {
    const ext = normalizeEditorPath(path).split('.').pop().toLowerCase();
    const langMap = {
      'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript',
      'tsx': 'typescript', 'html': 'html', 'css': 'css', 'json': 'json',
      'yaml': 'yaml', 'yml': 'yaml', 'md': 'markdown', 'java': 'java',
      'cpp': 'cpp', 'c': 'c', 'go': 'go', 'rs': 'rust', 'php': 'php',
      'rb': 'ruby', 'sh': 'shell', 'sql': 'sql'
    };
    return langMap[ext] || 'plaintext';
  }, []);

  const loadFile = useCallback(async (filePath) => {
    try {
      const normalizedPath = normalizeEditorPath(filePath);
      const existingFile = openFiles.find(f => f.path === normalizedPath);
      if (existingFile) {
        setActiveTab(normalizedPath);
        setEditorContent(existingFile.content);
        setEditorLanguage(existingFile.language);
        return;
      }

      const response = await ApiService.readFile(normalizedPath);
      const fileInfo = {
        path: normalizedPath,
        name: normalizedPath.split('/').pop() || 'untitled',
        content: response.content,
        language: getLanguageFromPath(normalizedPath),
        modified: false
      };

      setOpenFiles(prev => [...prev, fileInfo]);
      setActiveTab(normalizedPath);
      setEditorContent(response.content);
      setEditorLanguage(fileInfo.language);
      toast.success(`Opened ${fileInfo.name}`);
    } catch (error) {
      console.error('Error loading file:', error);
      toast.error(`Failed to load file: ${error.response?.data?.detail || error.message}`);
    }
  }, [getLanguageFromPath, openFiles]);

  useEffect(() => {
    if (selectedFile && !openFiles.find(f => f.path === selectedFile)) {
      loadFile(selectedFile);
    } else if (selectedFile && openFiles.find(f => f.path === selectedFile)) {
      const file = openFiles.find(f => f.path === selectedFile);
      setActiveTab(file.path);
      setEditorContent(file.content);
      setEditorLanguage(file.language);
    }
  }, [selectedFile, openFiles, loadFile]);

  // Auto-scroll chat to bottom
  useEffect(() => {
    const chatContainer = document.querySelector('.chat-messages-container');
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }, [chatMessages]);

  useEffect(() => {
    if (bottomPanelTab !== 'terminal') return;
    if (terminalOutputRef.current) {
      terminalOutputRef.current.scrollTop = terminalOutputRef.current.scrollHeight;
    }
  }, [terminalOutput, isTerminalBusy, bottomPanelTab]);

  // Close file suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (showFileSuggestions && 
          !e.target.closest('.file-suggestions-container') &&
          !e.target.closest('input[placeholder*="@"]') &&
          !e.target.closest('input[placeholder*="Type your message"]')) {
        setShowFileSuggestions(false);
      }
      
      // Close Auto dropdown when clicking outside
      if (showAutoDropdown && 
          !e.target.closest('[data-auto-dropdown]')) {
        setShowAutoDropdown(false);
      }
    };

    if (showFileSuggestions || showAutoDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showFileSuggestions, showAutoDropdown]);

  // Save file function
  const saveFile = useCallback(async (filePath, options = {}) => {
    try {
      const file = openFiles.find(f => f.path === filePath);
      if (!file) {
        toast.error('No file to save');
        return;
      }

      const targetPath = options.overridePath
        ? options.overridePath.replace(/\\/g, '/')
        : file.path;

      await ApiService.writeFile(targetPath, file.content);
      setOpenFiles(prev => prev.map(f => {
        if (f.path !== filePath) {
          return f;
        }
        const updatedFile = {
          ...f,
          path: targetPath,
          name: targetPath.split('/').pop() || f.name,
          modified: false
        };
        return updatedFile;
      }));

      if (activeTab === filePath) {
        setActiveTab(targetPath);
      }
      if (selectedFile === filePath) {
        setSelectedFile(targetPath);
      }

      toast.success(filePath !== targetPath ? `Saved as ${targetPath}` : `Saved ${file.name}`);
      await refreshFileTree();
    } catch (error) {
      console.error('Error saving file:', error);
      toast.error(`Failed to save file: ${error.response?.data?.detail || error.message}`);
    }
  }, [openFiles, activeTab, selectedFile, refreshFileTree]);

  const appendTerminalLine = useCallback((text, type = 'stdout') => {
    if (typeof text !== 'string') {
      return;
    }
    setTerminalOutput(prev => [...prev, { id: createUniqueLineId(), text, type }]);
  }, []);

  const focusTerminalInput = useCallback(() => {
    if (terminalInputRef.current) {
      terminalInputRef.current.focus();
    }
  }, []);

  const addCommandToHistory = useCallback((command) => {
    if (!command) {
      return;
    }
    setTerminalHistory((prev) => {
      const lastEntry = prev[prev.length - 1];
      if (lastEntry === command) {
        return prev;
      }
      const next = [...prev, command];
      if (next.length > MAX_TERMINAL_HISTORY) {
        next.splice(0, next.length - MAX_TERMINAL_HISTORY);
      }
      return next;
    });
  }, []);

  const showCompletionList = useCallback((completions = []) => {
    if (!Array.isArray(completions) || completions.length === 0) {
      appendTerminalLine('No matches', 'info');
      return;
    }
    for (let i = 0; i < completions.length; i += COMPLETION_LIST_COLUMNS) {
      const chunk = completions.slice(i, i + COMPLETION_LIST_COLUMNS).map((item) => item.value);
      appendTerminalLine(chunk.join('    '), 'info');
    }
  }, [appendTerminalLine]);

  const applyCompletionReplacement = useCallback((replacement) => {
    if (
      !replacement ||
      typeof replacement.start !== 'number' ||
      typeof replacement.end !== 'number'
    ) {
      return false;
    }
    const text = typeof replacement.text === 'string' ? replacement.text : '';
    const existing = terminalInput.slice(replacement.start, replacement.end);
    if (existing === text) {
      return false;
    }
    setTerminalInput((prev) => {
      const before = prev.slice(0, replacement.start);
      const after = prev.slice(replacement.end);
      const nextValue = `${before}${text}${after}`;
      requestAnimationFrame(() => {
        if (terminalInputRef.current) {
          const nextCursor = replacement.start + text.length;
          terminalInputRef.current.setSelectionRange(nextCursor, nextCursor);
          focusTerminalInput();
        }
      });
      return nextValue;
    });
    return true;
  }, [focusTerminalInput, terminalInput]);

  const processTerminalResponse = useCallback((response, options = {}) => {
    if (!response) {
      return response;
    }
    const { showExitCode = true } = options;

    if (response.session_id && response.session_id !== terminalSessionId) {
      setTerminalSessionId(response.session_id);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('terminalSessionId', response.session_id);
      }
    }

    if (response.cwd) {
      setTerminalCwd(response.cwd);
    }

    if (Array.isArray(response.stdout_lines) && response.stdout_lines.length > 0) {
      response.stdout_lines.forEach(line => appendTerminalLine(line, 'stdout'));
    } else if (response.stdout) {
      appendTerminalLine(response.stdout, 'stdout');
    }

    if (Array.isArray(response.stderr_lines) && response.stderr_lines.length > 0) {
      response.stderr_lines.forEach(line => appendTerminalLine(line, 'stderr'));
    } else if (response.stderr) {
      appendTerminalLine(response.stderr, 'stderr');
    }

    if (response.message) {
      appendTerminalLine(response.message, response.success ? 'info' : 'error');
    }

    if (response.timed_out) {
      appendTerminalLine(
        `Command exceeded the ${response.timeout_seconds || 120}s limit. Continuous tasks (e.g., "ping -t") are not yet supported; try using a bounded option such as "-n 5".`,
        'error'
      );
    }

    if (typeof response.exit_code === 'number' && showExitCode && !response.was_cd) {
      const type = response.exit_code === 0 ? 'info' : 'error';
      appendTerminalLine(`Process exited with code ${response.exit_code}`, type);
    }

    return response;
  }, [appendTerminalLine, setTerminalCwd, setTerminalSessionId, terminalSessionId]);

  const ensureTerminalVisible = useCallback(() => {
    setBottomPanelVisible(true);
    setBottomPanelTab('terminal');
  }, []);

  const handleTerminalCompletion = useCallback(async () => {
    if (!terminalSessionId || isCompletingTerminal) {
      return;
    }
    const cursorPosition = terminalInputRef.current?.selectionStart ?? terminalInput.length;
    const requestId = completionRequestIdRef.current + 1;
    completionRequestIdRef.current = requestId;
    setIsCompletingTerminal(true);
    try {
      const response = await ApiService.completeTerminalInput(
        terminalInput,
        terminalSessionId,
        cursorPosition
      );
      if (completionRequestIdRef.current !== requestId) {
        return;
      }

      const applied = response?.replacement
        ? applyCompletionReplacement(response.replacement)
        : false;
      const completions = Array.isArray(response?.completions) ? response.completions : [];

      if (completions.length === 0) {
        showCompletionList([]);
      } else if (!applied || completions.length > 1) {
        showCompletionList(completions);
      }
    } catch (error) {
      if (completionRequestIdRef.current === requestId) {
        console.error('Error completing terminal input:', error);
        appendTerminalLine(error.response?.data?.detail || error.message, 'error');
      }
    } finally {
      if (completionRequestIdRef.current === requestId) {
        setIsCompletingTerminal(false);
      }
    }
  }, [
    appendTerminalLine,
    applyCompletionReplacement,
    isCompletingTerminal,
    showCompletionList,
    terminalInput,
    terminalSessionId,
  ]);

  const handleHistoryNavigation = useCallback((direction) => {
    if (!terminalHistory.length) {
      return;
    }
    setHistoryIndex((prevIndex) => {
      if (direction === 'prev') {
        const nextIndex = prevIndex === null ? terminalHistory.length - 1 : Math.max(prevIndex - 1, 0);
        if (prevIndex === null) {
          historyDraftRef.current = terminalInput;
        }
        const command = terminalHistory[nextIndex] ?? '';
        setTerminalInput(command);
        requestAnimationFrame(() => {
          if (terminalInputRef.current) {
            const pos = command.length;
            terminalInputRef.current.setSelectionRange(pos, pos);
            focusTerminalInput();
          }
        });
        return nextIndex;
      }

      if (prevIndex === null) {
        return null;
      }

      const nextIndex = prevIndex + 1;
      if (nextIndex >= terminalHistory.length) {
        const draft = historyDraftRef.current || '';
        setTerminalInput(draft);
        requestAnimationFrame(() => {
          if (terminalInputRef.current) {
            const pos = draft.length;
            terminalInputRef.current.setSelectionRange(pos, pos);
            focusTerminalInput();
          }
        });
        historyDraftRef.current = '';
        return null;
      }

      const command = terminalHistory[nextIndex] ?? '';
      setTerminalInput(command);
      requestAnimationFrame(() => {
        if (terminalInputRef.current) {
          const pos = command.length;
          terminalInputRef.current.setSelectionRange(pos, pos);
          focusTerminalInput();
        }
      });
      return nextIndex;
    });
  }, [focusTerminalInput, terminalHistory, terminalInput]);

  const handleTerminalInputChange = useCallback((event) => {
    if (historyIndex !== null) {
      setHistoryIndex(null);
      historyDraftRef.current = '';
    }
    setTerminalInput(event.target.value);
  }, [historyIndex]);

  const runTerminalCommand = useCallback(async (command, options = {}) => {
    const { skipEcho = false } = options;
    const trimmed = command?.trim();
    if (!trimmed) return;
    if (isTerminalBusy) {
      toast.error('Terminal is busy');
      return;
    }
    ensureTerminalVisible();
    if (!skipEcho) {
      appendTerminalLine(`${terminalCwd}> ${trimmed}`, 'command');
    }
    setTerminalInput('');

    const lower = trimmed.toLowerCase();
    if (lower === 'clear' || lower === 'cls') {
      addCommandToHistory(trimmed);
      setHistoryIndex(null);
      historyDraftRef.current = '';
      setShowHistoryPanel(false);
      setHistoryFilter('');
      setTerminalOutput([]);
      return;
    }

    addCommandToHistory(trimmed);
    setHistoryIndex(null);
    historyDraftRef.current = '';
    setShowHistoryPanel(false);
    setHistoryFilter('');

    setIsTerminalBusy(true);
    try {
      const response = await ApiService.runTerminalCommand(trimmed, terminalSessionId);
      processTerminalResponse(response);
    } catch (error) {
      console.error('Error executing terminal command:', error);
      appendTerminalLine(error.response?.data?.detail || error.message, 'error');
    } finally {
      setIsTerminalBusy(false);
    }
  }, [
    addCommandToHistory,
    appendTerminalLine,
    ensureTerminalVisible,
    isTerminalBusy,
    processTerminalResponse,
    terminalCwd,
    terminalSessionId,
  ]);

  const handleQuickCommand = useCallback((command) => {
    if (!command) {
      return;
    }
    runTerminalCommand(command);
  }, [runTerminalCommand]);

  const handleClearTerminalOutput = useCallback(() => {
    setTerminalOutput([]);
  }, []);

  const handleHistoryEntrySelect = useCallback((command) => {
    if (typeof command !== 'string' || !command.length) {
      return;
    }
    setTerminalInput(command);
    setHistoryIndex(null);
    historyDraftRef.current = '';
    setShowHistoryPanel(false);
    requestAnimationFrame(() => {
      if (terminalInputRef.current) {
        const pos = command.length;
        terminalInputRef.current.setSelectionRange(pos, pos);
        focusTerminalInput();
      }
    });
  }, [focusTerminalInput]);

  const handleClearTerminalHistory = useCallback(() => {
    setTerminalHistory([]);
    setHistoryIndex(null);
    historyDraftRef.current = '';
    setHistoryFilter('');
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(TERMINAL_HISTORY_STORAGE_KEY);
    }
    appendTerminalLine('Cleared terminal history', 'info');
  }, [appendTerminalLine]);

  const handleHistoryPanelToggle = useCallback(() => {
    setShowHistoryPanel((prev) => !prev);
    requestAnimationFrame(() => {
      focusTerminalInput();
    });
  }, [focusTerminalInput]);

  const handleHistoryFilterChange = useCallback((event) => {
    setHistoryFilter(event.target.value);
  }, []);

  const handleStopTerminalCommand = useCallback(async () => {
    if (!terminalSessionId || !isTerminalBusy || isStoppingTerminal) {
      return;
    }
    setIsStoppingTerminal(true);
    try {
      const response = await ApiService.stopTerminalCommand(terminalSessionId);
      processTerminalResponse(response, { showExitCode: false });
    } catch (error) {
      console.error('Error interrupting terminal command:', error);
      appendTerminalLine(error.response?.data?.detail || error.message, 'error');
    } finally {
      setIsStoppingTerminal(false);
    }
  }, [appendTerminalLine, isStoppingTerminal, isTerminalBusy, processTerminalResponse, terminalSessionId]);

  const handleTerminalInputKeyDown = async (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      await handleTerminalCompletion();
      return;
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault();
      handleHistoryNavigation('prev');
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      handleHistoryNavigation('next');
      return;
    }

    if (e.ctrlKey && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      handleClearTerminalOutput();
      return;
    }

    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'h') {
      e.preventDefault();
      handleHistoryPanelToggle();
      return;
    }

    if (e.key === 'Enter' && !isTerminalBusy) {
      e.preventDefault();
      await runTerminalCommand(terminalInput);
    }
  };

  // Resize handlers
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isResizingLeft) {
        const newWidth = e.clientX;
        if (newWidth >= 200 && newWidth <= 600) {
          setLeftSidebarWidth(newWidth);
        }
      } else if (isResizingRight) {
        // Calculate from right edge of window
        const newWidth = window.innerWidth - e.clientX;
        if (newWidth >= 200 && newWidth <= 600) {
          setRightSidebarWidth(newWidth);
        }
      } else if (isResizingBottom) {
        // Get the main content area height and calculate from top
        const mainContentArea = document.querySelector('.flex-1.flex.overflow-hidden')?.parentElement;
        if (mainContentArea) {
          const rect = mainContentArea.getBoundingClientRect();
          const newHeight = rect.bottom - e.clientY;
          if (newHeight >= 150 && newHeight <= 600) {
            setBottomPanelHeight(newHeight);
          }
        }
      }
    };

    const handleMouseUp = () => {
      setIsResizingLeft(false);
      setIsResizingRight(false);
      setIsResizingBottom(false);
    };

    if (isResizingLeft || isResizingRight || isResizingBottom) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      if (isResizingBottom) {
        document.body.style.cursor = 'row-resize';
      } else {
        document.body.style.cursor = 'col-resize';
      }
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizingLeft, isResizingRight, isResizingBottom]);

  const handleStopChat = useCallback(() => {
    if (chatAbortController) {
      chatAbortController.abort();
      setIsLoadingChat(false);
      setChatAbortController(null);
      toast('Chat stopped');
    }
  }, [chatAbortController]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+Shift+X: Stop chat (allow in all contexts)
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'x') {
        e.preventDefault();
        handleStopChat();
        return;
      }

      // Don't trigger shortcuts when typing in inputs/textarea
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        // Allow Ctrl+S and Ctrl+P in inputs
        if (!(e.ctrlKey && (e.key === 's' || e.key === 'p'))) {
          return;
        }
      }
      
      // Ctrl+B: Toggle left sidebar (files)
      if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        setLeftSidebarVisible(prev => !prev);
      }
      
      // Ctrl+J: Toggle bottom panel (terminal)
      if (e.ctrlKey && e.key === 'j') {
        e.preventDefault();
        setBottomPanelVisible(prev => !prev);
      }
      
      // Ctrl+\: Toggle right sidebar (chat)
      if (e.ctrlKey && e.key === '\\') {
        e.preventDefault();
        setRightSidebarVisible(prev => !prev);
      }

      // Ctrl+S: Save current file
      if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        if (activeTab) {
          saveFile(activeTab);
        }
      }

      // Ctrl+P: Focus search
      if (e.ctrlKey && e.key === 'p') {
        e.preventDefault();
        focusSearchInput();
      }

      if (e.ctrlKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        ensureTerminalVisible();
        if (terminalInputRef.current) {
          terminalInputRef.current.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeTab, saveFile, focusSearchInput, ensureTerminalVisible, handleStopChat]);

  const resolvePathInput = (inputPath) => {
    if (!inputPath) return null;
    const trimmed = inputPath.trim();
    if (!trimmed) return null;
    if (trimmed === '.' || trimmed === './') {
      return currentPath || '.';
    }
    if (/^[a-zA-Z]:/.test(trimmed) || trimmed.startsWith('/')) {
      return trimmed.replace(/\\/g, '/');
    }
    if (!currentPath || currentPath === '.' || currentPath === './') {
      return trimmed.replace(/\\/g, '/');
    }
    return `${currentPath}/${trimmed}`.replace(/\\/g, '/');
  };

  const getParentDirectory = useCallback((path) => {
    if (!path) return '.';
    const normalized = normalizeEditorPath(path);
    const segments = normalized.split('/');
    segments.pop();
    const parent = segments.join('/');
    return parent || '.';
  }, []);

  const joinPaths = useCallback((basePath, childName) => {
    const normalizedBase = normalizeEditorPath(basePath || '.').replace(/\/$/, '');
    if (!childName) return normalizedBase || '.';
    if (!normalizedBase || normalizedBase === '.' || normalizedBase === '') {
      return normalizeEditorPath(childName);
    }
    return `${normalizedBase}/${childName}`.replace(/\/{2,}/g, '/');
  }, []);

  const getRelativePath = useCallback((targetPath) => {
    if (!targetPath) return '';
    const basePath = normalizeEditorPath(projectRoot?.path || '.');
    const normalizedTarget = normalizeEditorPath(targetPath);
    if (!basePath || basePath === '.' || !normalizedTarget.startsWith(basePath)) {
      return normalizedTarget;
    }
    const relative = normalizedTarget.slice(basePath.length).replace(/^\/+/, '');
    return relative || normalizedTarget.split('/').pop() || normalizedTarget;
  }, [projectRoot?.path]);

  const quotePath = useCallback((path) => `"${path.replace(/"/g, '\\"')}"`, []);

  const loadPickerTree = useCallback(async (path = '.') => {
    try {
      setPickerLoading(true);
      const response = await ApiService.getFileTree(path, 1);
      if (response?.tree) {
        const normalizedTree = normalizeTreeNode(response.tree);
        setPickerTree(normalizedTree.children || []);
        setPickerPath(normalizedTree.path || '.');
      }
    } catch (error) {
      console.error('Error loading picker tree:', error);
      toast.error('Failed to load directory');
    } finally {
      setPickerLoading(false);
    }
  }, []);

  const handleCreateFile = useCallback(async (basePath = null) => {
    const targetBase = basePath || currentPath || '.';
    setPickerMode('file');
    setPickerPath(targetBase);
    setPickerSelectedPath('');
    setShowFilePicker(true);
    await loadPickerTree(targetBase);
  }, [currentPath, loadPickerTree]);

  const handleFilePickerConfirm = async () => {
    const inputPath = pickerSelectedPath || '';
    if (!inputPath) {
      toast.error('Please enter a file path');
      return;
    }
    const resolvedPath = resolvePathInput(inputPath);
    if (!resolvedPath) return;
    try {
      await ApiService.writeFile(resolvedPath, '');
      const language = getLanguageFromPath(resolvedPath);
      const fileInfo = {
        path: resolvedPath,
        name: resolvedPath.split('/').pop() || resolvedPath,
        content: '',
        language,
        modified: false
      };
      setOpenFiles(prev => [...prev, fileInfo]);
      setActiveTab(resolvedPath);
      setEditorContent('');
      setEditorLanguage(language);
      toast.success(`Created ${fileInfo.name}`);
      await refreshFileTree();
      setShowFilePicker(false);
    } catch (error) {
      console.error('Error creating file:', error);
      toast.error(`Failed to create file: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleCreateFolder = useCallback(async (basePath = null) => {
    const targetBase = basePath || currentPath || '.';
    setPickerMode('folder');
    setPickerPath(targetBase);
    setPickerSelectedPath('');
    setShowFilePicker(true);
    await loadPickerTree(targetBase);
  }, [currentPath, loadPickerTree]);

  const handleFolderPickerConfirm = async () => {
    const inputPath = pickerSelectedPath || '';
    if (!inputPath) {
      toast.error('Please enter a folder path');
      return;
    }
    const resolvedPath = resolvePathInput(inputPath);
    if (!resolvedPath) return;
    try {
      await ApiService.createDirectory(resolvedPath);
      toast.success(`Created folder ${resolvedPath}`);
      await refreshFileTree();
      setShowFilePicker(false);
    } catch (error) {
      console.error('Error creating folder:', error);
      toast.error(`Failed to create folder: ${error.response?.data?.detail || error.message}`);
    }
  };

  useEffect(() => {
    if (!fileContextMenu.visible) {
      return;
    }
    const handleClick = (event) => {
      if (!(event.target.closest && event.target.closest('.file-context-menu'))) {
        closeFileContextMenu();
      }
    };
    const handleScroll = () => closeFileContextMenu();
    const handleKey = (event) => {
      if (event.key === 'Escape') {
        closeFileContextMenu();
      }
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('scroll', handleScroll, true);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('scroll', handleScroll, true);
      document.removeEventListener('keydown', handleKey);
    };
  }, [closeFileContextMenu, fileContextMenu.visible]);

  const handleCopyPathValue = useCallback(async (path, options = {}) => {
    if (!path || !navigator?.clipboard?.writeText) {
      toast.error('Clipboard API unavailable');
      return;
    }
    try {
      const value = options.relative ? getRelativePath(path) : normalizeEditorPath(path);
      await navigator.clipboard.writeText(value);
      toast.success(options.relative ? 'Relative path copied' : 'Path copied');
    } catch (error) {
      console.error('Copy path failed:', error);
      toast.error('Failed to copy path');
    } finally {
      closeFileContextMenu();
    }
  }, [closeFileContextMenu, getRelativePath]);

  const handleCopyShareLink = useCallback(async (target, variant = 'markdown') => {
    if (!target || !navigator?.clipboard?.writeText) {
      toast.error('Clipboard API unavailable');
      return;
    }
    try {
      const relative = getRelativePath(target.path);
      const normalized = normalizeEditorPath(target.path).replace(/\\/g, '/');
      let payload = normalized;
      if (variant === 'markdown') {
        payload = `[${target.name}](${relative})`;
      } else if (variant === 'file') {
        const prefix = normalized.startsWith('/') ? '' : '/';
        payload = `file://${prefix}${normalized}`;
      }
      await navigator.clipboard.writeText(payload);
      toast.success('Shareable link copied');
    } catch (error) {
      console.error('Copy share link failed:', error);
      toast.error('Failed to copy share link');
    } finally {
      closeFileContextMenu();
    }
  }, [closeFileContextMenu, getRelativePath]);

  const handleRevealInExplorer = useCallback((target) => {
    if (!target?.path) return;
    const normalized = normalizeEditorPath(target.path).replace(/\\/g, '/');
    let fileUrl = normalized;
    if (/^[a-zA-Z]:/.test(normalized)) {
      fileUrl = `/${normalized}`;
    }
    const encoded = fileUrl.replace(/ /g, '%20');
    window.open(`file://${encoded}`, '_blank', 'noopener,noreferrer');
  }, []);

  const handleOpenInTerminal = useCallback(async (target) => {
    if (!target?.path) return;
    const destination = target.is_directory ? target.path : getParentDirectory(target.path);
    if (!destination) return;
    ensureTerminalVisible();
    setBottomPanelTab('terminal');
    const command = isWindowsPlatform
      ? `cd /d "${destination}"`
      : `cd "${destination}"`;
    closeFileContextMenu();
    await runTerminalCommand(command);
  }, [closeFileContextMenu, ensureTerminalVisible, getParentDirectory, isWindowsPlatform, runTerminalCommand]);

  const handleAddPathToChat = useCallback((target, options = {}) => {
    if (!target?.path) return;
    const mention = `@${getRelativePath(target.path) || target.name}`;
    if (options.newTab) {
      const newId = Math.max(...chatTabs.map(t => t.id), 0) + 1;
      setChatTabs(prev => prev.map(tab => ({ ...tab, isActive: false })).concat([{ id: newId, title: 'New Chat', isActive: true }]));
      setActiveChatTab(newId);
      setChatMessages([]);
      setComposerInput(mention);
    } else {
      setComposerInput(prev => (prev ? `${prev.trim()} ${mention}` : mention));
      requestAnimationFrame(() => composerInputRef.current?.focus());
    }
    toast.success('Path added to chat input');
    closeFileContextMenu();
  }, [chatTabs, closeFileContextMenu, composerInputRef, getRelativePath]);

  const handleFindInFolder = useCallback(async (target) => {
    if (!target) return;
    const folderPath = target.is_directory ? target.path : getParentDirectory(target.path);
    if (!folderPath) return;
    const query = window.prompt(`Search within ${folderPath}`, '');
    if (!query) return;
    try {
      const response = await ApiService.searchFiles(query, folderPath);
      setFolderSearchResults({
        folderPath,
        query,
        results: response.results || [],
      });
      toast.success(`Found ${response.results?.length || 0} result(s)`);
    } catch (error) {
      console.error('Find in folder failed:', error);
      toast.error('Failed to search within folder');
    } finally {
      closeFileContextMenu();
    }
  }, [closeFileContextMenu, getParentDirectory]);

  const handleCompareWithTarget = useCallback(async (target) => {
    if (!target || target.is_directory) {
      toast.error('Select a file to compare');
      return;
    }
    if (!compareSource) {
      setCompareSource(target);
      toast('Select another file to complete the comparison');
      closeFileContextMenu();
      return;
    }
    if (compareSource.path === target.path) {
      toast.error('Select a different file to compare');
      return;
    }
    try {
      const [a, b] = await Promise.all([
        ApiService.readFile(compareSource.path),
        ApiService.readFile(target.path),
      ]);
      const diff = computeLineDiff(a.content, b.content);
      setComparisonState({
        leftLabel: compareSource.name || 'File A',
        rightLabel: target.name || 'File B',
        leftPath: compareSource.path,
        rightPath: target.path,
        diff,
      });
      setCompareSource(null);
    } catch (error) {
      console.error('Compare failed:', error);
      toast.error('Failed to compare files');
    } finally {
      closeFileContextMenu();
    }
  }, [closeFileContextMenu, compareSource]);

  const handleCompareWithClipboard = useCallback(async (target) => {
    if (!target || target.is_directory) {
      toast.error('Select a file to compare');
      return;
    }
    try {
      const clipboardText = await navigator.clipboard.readText();
      const fileData = await ApiService.readFile(target.path);
      const diff = computeLineDiff(clipboardText, fileData.content);
      setComparisonState({
        leftLabel: 'Clipboard',
        rightLabel: target.name || 'File',
        leftPath: 'Clipboard',
        rightPath: target.path,
        diff,
      });
      closeFileContextMenu();
    } catch (error) {
      console.error('Compare with clipboard failed:', error);
      toast.error('Failed to compare with clipboard');
    }
  }, [closeFileContextMenu]);

  const handleCutOrCopy = useCallback((target, action) => {
    if (!target) return;
    setFileClipboard({ action, item: target });
    toast.success(action === 'cut' ? 'Ready to move item' : 'Item copied');
    closeFileContextMenu();
  }, [closeFileContextMenu]);

  const applyPathRename = useCallback((oldPath, newPath, isDirectory) => {
    if (!oldPath || !newPath) return;
    const normalizedOld = normalizeEditorPath(oldPath);
    const normalizedNew = normalizeEditorPath(newPath);
    setOpenFiles(prev =>
      prev.map(file => {
        if (!file.path.startsWith(normalizedOld)) {
          return file;
        }
        const suffix = file.path.slice(normalizedOld.length);
        const updatedPath = `${normalizedNew}${suffix}`;
        return {
          ...file,
          path: updatedPath,
          name: updatedPath.split('/').pop() || file.name,
        };
      })
    );
    if (selectedFile?.startsWith(normalizedOld)) {
      const suffix = selectedFile.slice(normalizedOld.length);
      setSelectedFile(`${normalizedNew}${suffix}`);
    }
    if (activeTab?.startsWith(normalizedOld)) {
      const suffix = activeTab.slice(normalizedOld.length);
      const updated = `${normalizedNew}${suffix}`;
      setActiveTab(updated);
    }
    setExpandedFolders(prev => {
      const next = new Set();
      prev.forEach((path) => {
        if (path.startsWith(normalizedOld)) {
          next.add(`${normalizedNew}${path.slice(normalizedOld.length)}`);
        } else {
          next.add(path);
        }
      });
      if (isDirectory) {
        next.add(normalizedNew);
      }
      return next;
    });
  }, [activeTab, selectedFile]);

  const removePathReferences = useCallback((targetPath) => {
    if (!targetPath) return;
    const normalized = normalizeEditorPath(targetPath);
    setOpenFiles(prev => prev.filter(file => !file.path.startsWith(normalized)));
    if (selectedFile?.startsWith(normalized)) {
      setSelectedFile(null);
    }
    if (activeTab?.startsWith(normalized)) {
      setActiveTab(null);
      setEditorContent('');
    }
    setExpandedFolders(prev => {
      const next = new Set();
      prev.forEach((path) => {
        if (!path.startsWith(normalized)) {
          next.add(path);
        }
      });
      return next;
    });
  }, [activeTab, selectedFile]);

  const handlePasteInto = useCallback(async (target) => {
    if (!fileClipboard?.item) {
      toast.error('Nothing to paste');
      return;
    }
    const destinationDir = target?.is_directory
      ? target.path
      : getParentDirectory(target?.path || fileClipboard.item.path);
    if (!destinationDir) {
      toast.error('Select a destination folder');
      return;
    }
    const sourcePath = fileClipboard.item.path;
    const destinationPath = joinPaths(destinationDir, fileClipboard.item.name || sourcePath.split('/').pop());
    if (normalizeEditorPath(destinationPath) === normalizeEditorPath(sourcePath)) {
      toast.error('Source and destination are identical');
      return;
    }
    try {
      if (fileClipboard.action === 'copy') {
        await ApiService.copyPath(sourcePath, destinationPath);
        toast.success('Item copied');
      } else {
        await ApiService.movePath(sourcePath, destinationPath);
        applyPathRename(sourcePath, destinationPath, fileClipboard.item.is_directory);
        setFileClipboard(null);
        toast.success('Item moved');
      }
      await refreshFileTree();
    } catch (error) {
      console.error('Paste failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to paste item');
    } finally {
      closeFileContextMenu();
    }
  }, [applyPathRename, closeFileContextMenu, fileClipboard, getParentDirectory, joinPaths, refreshFileTree]);

  const handleRenamePath = useCallback(async (target) => {
    if (!target) return;
    const newName = window.prompt('Enter a new name', target.name);
    if (!newName || newName === target.name) return;
    const destination = joinPaths(getParentDirectory(target.path), newName);
    try {
      await ApiService.movePath(target.path, destination);
      applyPathRename(target.path, destination, target.is_directory);
      toast.success('Renamed successfully');
      await refreshFileTree();
    } catch (error) {
      console.error('Rename failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to rename');
    } finally {
      closeFileContextMenu();
    }
  }, [applyPathRename, closeFileContextMenu, getParentDirectory, joinPaths, refreshFileTree]);

  const handleDeletePath = useCallback(async (target) => {
    if (!target) return;
    const confirmed = window.confirm(`Delete ${target.name}? This cannot be undone.`);
    if (!confirmed) return;
    try {
      await ApiService.deleteFile(target.path);
      removePathReferences(target.path);
      toast.success('Deleted successfully');
      await refreshFileTree();
    } catch (error) {
      console.error('Delete failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to delete');
    } finally {
      closeFileContextMenu();
    }
  }, [closeFileContextMenu, refreshFileTree, removePathReferences]);

  const handleRunTestsForPath = useCallback((target, mode = 'run') => {
    if (!target?.path) return;
    const normalized = normalizeEditorPath(target.path);
    const ext = target.is_directory ? '' : normalized.split('.').pop().toLowerCase();
    const quoted = quotePath(normalized);
    let command = null;
    if (!ext || ['js', 'jsx', 'ts', 'tsx'].includes(ext)) {
      if (mode === 'coverage') {
        command = `npm test -- --coverage ${quoted}`;
      } else if (mode === 'debug') {
        command = `npm test -- --runInBand ${quoted}`;
      } else {
        command = `npm test -- ${quoted}`;
      }
    } else if (ext === 'py' || (!ext && normalized.endsWith('/'))) {
      if (mode === 'coverage') {
        command = `pytest --maxfail=1 --cov ${quoted}`;
      } else if (mode === 'debug') {
        command = `pytest -vv ${quoted}`;
      } else {
        command = `pytest ${quoted}`;
      }
    }
    if (!command) {
      toast.error('Unsupported file type for test command');
      return;
    }
    runTerminalCommand(command);
    closeFileContextMenu();
  }, [closeFileContextMenu, quotePath, runTerminalCommand]);

  const contextMenuItems = useMemo(() => {
    const target = fileContextMenu.target;
    if (!target) {
      return [];
    }
    const isDirectory = !!target.is_directory;
    const basePath = isDirectory ? target.path : getParentDirectory(target.path);
    const fileTypeLabel = isDirectory ? 'Directory' : 'File';
    return [
      {
        label: 'Compare with...',
        disabled: isDirectory,
        action: () => handleCompareWithTarget(target),
      },
      {
        label: 'Compare with clipboard',
        disabled: isDirectory,
        action: () => handleCompareWithClipboard(target),
      },
      { type: 'separator' },
      {
        label: 'New File...',
        action: () => handleCreateFile(basePath),
      },
      {
        label: 'New Folder...',
        action: () => handleCreateFolder(basePath),
      },
      { type: 'separator' },
      {
        label: 'Reveal in File Explorer',
        shortcut: 'Shift+Alt+R',
        action: () => handleRevealInExplorer(target),
      },
      {
        label: 'Open in Integrated Terminal',
        action: () => handleOpenInTerminal(target),
      },
      { type: 'separator' },
      {
        label: 'Share',
        children: [
          {
            label: 'Copy Markdown link',
            action: () => handleCopyShareLink(target, 'markdown'),
          },
          {
            label: 'Copy file:// link',
            action: () => handleCopyShareLink(target, 'file'),
          },
        ],
      },
      {
        label: `Add ${fileTypeLabel} to Cursor Chat`,
        action: () => handleAddPathToChat(target),
      },
      {
        label: `Add ${fileTypeLabel} to New Cursor Chat`,
        action: () => handleAddPathToChat(target, { newTab: true }),
      },
      {
        label: 'Find in Folder...',
        shortcut: 'Shift+Alt+F',
        action: () => handleFindInFolder(target),
      },
      { type: 'separator' },
      {
        label: 'Cut',
        shortcut: 'Ctrl+X',
        action: () => handleCutOrCopy(target, 'cut'),
      },
      {
        label: 'Copy',
        shortcut: 'Ctrl+C',
        action: () => handleCutOrCopy(target, 'copy'),
      },
      {
        label: 'Paste',
        shortcut: 'Ctrl+V',
        disabled: !fileClipboard,
        action: () => handlePasteInto(target),
      },
      { type: 'separator' },
      {
        label: 'Copy Path',
        shortcut: 'Shift+Alt+C',
        action: () => handleCopyPathValue(target.path),
      },
      {
        label: 'Copy Relative Path',
        shortcut: 'Ctrl+M Ctrl+Shift+C',
        action: () => handleCopyPathValue(target.path, { relative: true }),
      },
      { type: 'separator' },
      {
        label: 'Run Tests',
        action: () => handleRunTestsForPath(target, 'run'),
      },
      {
        label: 'Debug Tests',
        action: () => handleRunTestsForPath(target, 'debug'),
      },
      {
        label: 'Run Tests with Coverage',
        action: () => handleRunTestsForPath(target, 'coverage'),
      },
      { type: 'separator' },
      {
        label: 'Rename...',
        shortcut: 'F2',
        action: () => handleRenamePath(target),
      },
      {
        label: 'Delete',
        shortcut: 'Delete',
        action: () => handleDeletePath(target),
      },
    ];
  }, [
    fileClipboard,
    fileContextMenu.target,
    getParentDirectory,
    handleAddPathToChat,
    handleCompareWithClipboard,
    handleCompareWithTarget,
    handleCopyPathValue,
    handleCopyShareLink,
    handleCreateFile,
    handleCreateFolder,
    handleCutOrCopy,
    handleDeletePath,
    handleFindInFolder,
    handleOpenInTerminal,
    handlePasteInto,
    handleRenamePath,
    handleRevealInExplorer,
    handleRunTestsForPath,
  ]);

  const handleFileContextMenu = useCallback((event, target) => {
    if (event?.button === 0 && event?.ctrlKey && typeof event?.metaKey === 'boolean') {
      return;
    }
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (!target) return;
    const MENU_WIDTH = 280;
    const MENU_HEIGHT = 480;
    const x = Math.min(event?.clientX ?? 0, window.innerWidth - MENU_WIDTH);
    const y = Math.min(event?.clientY ?? 0, window.innerHeight - MENU_HEIGHT);
    setFileContextMenu({
      visible: true,
      x: Math.max(8, x),
      y: Math.max(8, y),
      target,
    });
  }, []);

  const handleOpenFolderPrompt = async () => {
    setPickerMode('folder');
    setPickerPath(currentPath || '.');
    setPickerSelectedPath('');
    setShowFolderPicker(true);
    await loadPickerTree(currentPath || '.');
  };

  const handleFolderPickerSelect = async () => {
    if (!pickerSelectedPath) {
      // If no selection, use current path
      await loadProjectTree(pickerPath, { setAsRoot: true, showToastMessage: true });
    } else {
      await loadProjectTree(pickerSelectedPath, { setAsRoot: true, showToastMessage: true });
    }
    setShowFolderPicker(false);
  };

  const handleOpenFolderFromTree = async (folderPath) => {
    if (!folderPath) return;
    await loadProjectTree(folderPath, { setAsRoot: true, showToastMessage: true });
  };

  const buildRunCommandForActiveFile = () => {
    if (!activeTab) return null;
    const quotedPath = quotePath(activeTab);
    switch (editorLanguage) {
      case 'python':
        return `python ${quotedPath}`;
      case 'javascript':
        return `node ${quotedPath}`;
      case 'typescript':
        return `ts-node ${quotedPath}`;
      case 'shell':
        return `bash ${quotedPath}`;
      case 'go':
        return `go run ${quotedPath}`;
      default:
        return null;
    }
  };

  const ensureEditorReady = useCallback(() => {
    if (!isEditorReady || !editorRef.current) {
      toast.error('Open a file to use editor commands');
      return false;
    }
    return true;
  }, [isEditorReady]);

  const triggerEditorCommand = useCallback((commandId, payload = null) => {
    if (!ensureEditorReady()) return;
    editorRef.current.focus();
    editorRef.current.trigger('menu', commandId, payload);
  }, [ensureEditorReady]);

  const handleRunActiveFile = () => {
    const command = buildRunCommandForActiveFile();
    if (!command) {
      toast.error('Cannot determine how to run this file');
      return;
    }
    runTerminalCommand(command);
  };

  const handleRunTests = () => {
    const command = window.prompt('Enter test command to run:', 'npm test');
    if (command && command.trim()) {
      runTerminalCommand(command.trim());
    }
  };

  const handleRunCustomCommand = () => {
    const command = window.prompt('Enter command to run:');
    if (command && command.trim()) {
      runTerminalCommand(command.trim());
    }
  };

  const handleSaveAs = async () => {
    if (!activeTab) return;
    setPickerMode('file');
    setPickerPath(activeTab.split('/').slice(0, -1).join('/') || '.');
    setPickerSelectedPath(activeTab);
    setShowFilePicker(true);
    const parentPath = activeTab.split('/').slice(0, -1).join('/') || '.';
    await loadPickerTree(parentPath);
  };

  const handleSaveAsConfirm = async () => {
    if (!activeTab) return;
    const newPath = pickerSelectedPath || activeTab;
    const resolvedPath = resolvePathInput(newPath);
    if (!resolvedPath) return;
    await saveFile(activeTab, { overridePath: resolvedPath });
    setShowFilePicker(false);
  };

  const toggleMinimap = () => {
    setEditorOptions(prev => ({
      ...prev,
      minimap: { enabled: !prev.minimap?.enabled }
    }));
  };

  const toggleWordWrap = () => {
    setEditorOptions(prev => ({
      ...prev,
      wordWrap: prev.wordWrap === 'on' ? 'off' : 'on'
    }));
  };

  const resetLayout = () => {
    setLeftSidebarVisible(true);
    setRightSidebarVisible(true);
    setBottomPanelVisible(true);
    setLeftSidebarWidth(256);
    setRightSidebarWidth(320);
    setBottomPanelHeight(256);
    setBottomPanelTab('terminal');
  };

  const toggleLeftSidebarVisibility = () => setLeftSidebarVisible(prev => !prev);
  const toggleRightSidebarVisibility = () => setRightSidebarVisible(prev => !prev);
  const toggleBottomPanelVisibility = () => {
    setBottomPanelVisible(prev => {
      const next = !prev;
      if (next) {
        setBottomPanelTab('terminal');
      }
      return next;
    });
  };

  const handleUndo = () => triggerEditorCommand('undo');
  const handleRedo = () => triggerEditorCommand('redo');
  const handleCut = () => triggerEditorCommand('editor.action.clipboardCutAction');
  const handleCopy = () => triggerEditorCommand('editor.action.clipboardCopyAction');
  const handlePaste = () => triggerEditorCommand('editor.action.clipboardPasteAction');
  const handleFind = () => triggerEditorCommand('actions.find');
  const handleReplace = () => triggerEditorCommand('editor.action.startFindReplaceAction');
  const handleFormatDocument = () => triggerEditorCommand('editor.action.formatDocument');
  const handleSelectAll = () => triggerEditorCommand('editor.action.selectAll');
  const handleExpandSelection = () => triggerEditorCommand('editor.action.smartSelect.grow');
  const handleShrinkSelection = () => triggerEditorCommand('editor.action.smartSelect.shrink');
  const handleGoToLine = () => triggerEditorCommand('editor.action.gotoLine');
  const handleGoToDefinition = () => triggerEditorCommand('editor.action.revealDefinition');
  const handleGoToSymbol = () => triggerEditorCommand('editor.action.gotoSymbol');
  const handleToggleComment = () => triggerEditorCommand('editor.action.commentLine');
  const handleGoToFile = () => focusSearchInput();
  const handleShowTerminalPanel = () => ensureTerminalVisible();

  const fileMenuItems = [
    { label: 'New File', shortcut: 'Ctrl+N', onSelect: handleCreateFile },
    { label: 'New Folder', onSelect: handleCreateFolder },
    { type: 'separator' },
    { label: 'Open File...', shortcut: 'Ctrl+P', onSelect: handleGoToFile },
    { label: 'Open Folder...', onSelect: handleOpenFolderPrompt },
    { label: 'Refresh Explorer', shortcut: 'F5', onSelect: handleRefreshExplorer },
    { type: 'separator' },
    { label: 'Save', shortcut: 'Ctrl+S', onSelect: () => activeTab && saveFile(activeTab), disabled: !activeTab },
    { label: 'Save As...', onSelect: handleSaveAs, disabled: !activeTab },
  ];

  const editMenuItems = [
    { label: 'Undo', shortcut: 'Ctrl+Z', onSelect: handleUndo, disabled: !isEditorReady },
    { label: 'Redo', shortcut: 'Ctrl+Y', onSelect: handleRedo, disabled: !isEditorReady },
    { type: 'separator' },
    { label: 'Cut', shortcut: 'Ctrl+X', onSelect: handleCut, disabled: !isEditorReady },
    { label: 'Copy', shortcut: 'Ctrl+C', onSelect: handleCopy, disabled: !isEditorReady },
    { label: 'Paste', shortcut: 'Ctrl+V', onSelect: handlePaste, disabled: !isEditorReady },
    { type: 'separator' },
    { label: 'Find', shortcut: 'Ctrl+F', onSelect: handleFind, disabled: !isEditorReady },
    { label: 'Replace', shortcut: 'Ctrl+H', onSelect: handleReplace, disabled: !isEditorReady },
    { label: 'Format Document', shortcut: 'Shift+Alt+F', onSelect: handleFormatDocument, disabled: !isEditorReady },
  ];

  const selectionMenuItems = [
    { label: 'Select All', shortcut: 'Ctrl+A', onSelect: handleSelectAll, disabled: !isEditorReady },
    { label: 'Expand Selection', shortcut: 'Shift+Alt+→', onSelect: handleExpandSelection, disabled: !isEditorReady },
    { label: 'Shrink Selection', shortcut: 'Shift+Alt+←', onSelect: handleShrinkSelection, disabled: !isEditorReady },
    { label: 'Toggle Line Comment', shortcut: 'Ctrl+/', onSelect: handleToggleComment, disabled: !isEditorReady },
  ];

  const viewMenuItems = [
    { label: 'Toggle File Explorer', shortcut: 'Ctrl+B', onSelect: toggleLeftSidebarVisibility },
    { label: 'Toggle Chat', shortcut: 'Ctrl+\\', onSelect: toggleRightSidebarVisibility },
    { label: 'Toggle Terminal', shortcut: 'Ctrl+J', onSelect: toggleBottomPanelVisibility },
    { type: 'separator' },
    { label: 'Toggle Minimap', onSelect: toggleMinimap },
    { label: 'Toggle Word Wrap', onSelect: toggleWordWrap },
    { type: 'separator' },
    { label: 'Reset Layout', onSelect: resetLayout },
  ];

  const goMenuItems = [
    { label: 'Go to File...', shortcut: 'Ctrl+P', onSelect: handleGoToFile },
    { label: 'Go to Line...', shortcut: 'Ctrl+G', onSelect: handleGoToLine, disabled: !isEditorReady },
    { label: 'Go to Definition', shortcut: 'F12', onSelect: handleGoToDefinition, disabled: !isEditorReady },
    { label: 'Go to Symbol...', shortcut: 'Ctrl+Shift+O', onSelect: handleGoToSymbol, disabled: !isEditorReady },
  ];

  const runMenuItems = [
    { label: 'Run Active File', shortcut: 'Ctrl+Alt+N', onSelect: handleRunActiveFile, disabled: !activeTab },
    { label: 'Run Tests...', onSelect: handleRunTests },
    { label: 'Custom Command...', onSelect: handleRunCustomCommand },
    { type: 'separator' },
    { label: 'Show Terminal', onSelect: handleShowTerminalPanel },
  ];

  const handleFileClick = (file, e) => {
    if (file.is_directory) {
      // For folders, single click toggles expand/collapse
      if (e && e.detail === 2) {
        // Double click opens folder as root
        e.stopPropagation();
        handleOpenFolderFromTree(file.path);
      } else {
        toggleFolder(file.path);
      }
    } else {
      // For files, single click selects, double click opens
      const normalizedPath = file.path.replace(/\\/g, '/');
      if (e && e.detail === 2) {
        // Double click opens file
        loadFile(normalizedPath);
      } else {
        // Single click selects
        setSelectedFile(normalizedPath);
      }
    }
  };

  const toggleFolder = async (path) => {
    const isCurrentlyExpanded = expandedFolders.has(path);
    
    if (!isCurrentlyExpanded) {
      // Expanding - check if we need to load children
      const findFolderInTree = (nodes, targetPath) => {
        for (const node of nodes) {
          if (node.path === targetPath) return node;
          if (node.children) {
            const found = findFolderInTree(node.children, targetPath);
            if (found) return found;
          }
        }
        return null;
      };
      
      const folder = findFolderInTree(fileTree, path);
      
      // If folder exists but has no children loaded, or has_more_children flag, load them
      if (folder && (!folder.children || folder.children.length === 0 || folder.has_more_children)) {
        try {
          setIsFileTreeLoading(true);
          const response = await ApiService.getFileTree(path, 1); // Load only immediate children
          
          if (response?.tree) {
            const normalizedTree = normalizeTreeNode(response.tree);
            
            // Update the file tree to include the loaded children
            const updateTreeWithChildren = (nodes) => {
              return nodes.map(node => {
                if (node.path === path) {
                  return {
                    ...node,
                    children: normalizedTree.children || [],
                    has_more_children: false
                  };
                }
                if (node.children) {
                  return {
                    ...node,
                    children: updateTreeWithChildren(node.children)
                  };
                }
                return node;
              });
            };
            
            setFileTree(prev => updateTreeWithChildren(prev));
          }
        } catch (error) {
          console.error('Error loading folder children:', error);
          toast.error(`Failed to load folder: ${error.response?.data?.detail || error.message}`);
        } finally {
          setIsFileTreeLoading(false);
        }
      }
    }
    
    // Toggle expansion state
    setExpandedFolders(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  // Detect file mentions in message
  const detectFileMentions = (message) => {
    const mentionRegex = /@(\S+)/g;
    const mentions = [];
    let match;
    while ((match = mentionRegex.exec(message)) !== null) {
      mentions.push(match[1]);
    }
    return mentions;
  };

  // Simplify file tree for context (remove circular references)
  const simplifyFileTree = (tree) => {
    return tree.map(item => ({
      name: item.name,
      path: item.path,
      is_directory: item.is_directory,
      children: item.children ? simplifyFileTree(item.children) : []
    }));
  };

  // Get file suggestions based on open files and cached file tree nodes
  const getFileSuggestions = useCallback((query = '') => {
    const suggestions = [];
    const seenPaths = new Set();
    const normalizedQuery = (query || '').toLowerCase();

    const matchesQuery = (name = '', path = '') => {
      if (!normalizedQuery) return true;
      const lowerName = name.toLowerCase();
      const lowerPath = path.toLowerCase();
      return lowerName.includes(normalizedQuery) || lowerPath.includes(normalizedQuery);
    };

    const addSuggestion = (item, meta) => {
      if (!item?.path || seenPaths.has(item.path)) {
        return;
      }
      seenPaths.add(item.path);
      suggestions.push({
        path: item.path,
        name: item.name,
        type: meta.type,
        isOpen: meta.isOpen,
        displayPath: formatDisplayPath(item.path)
      });
    };

    for (const file of openFiles) {
      if (!matchesQuery(file.name, file.path)) continue;
      addSuggestion(file, { type: 'open', isOpen: true });
      if (suggestions.length >= MAX_FILE_SUGGESTIONS) {
        return suggestions.slice(0, MAX_FILE_SUGGESTIONS);
      }
    }

    for (const node of flattenedFileNodes) {
      if (suggestions.length >= MAX_FILE_SUGGESTIONS) {
        break;
      }
      if (!matchesQuery(node.name, node.path)) {
        continue;
      }
      addSuggestion(node, { type: 'file', isOpen: false });
    }

    return suggestions;
  }, [openFiles, flattenedFileNodes, formatDisplayPath]);

  const planStatusStyles = {
    completed: 'border-green-700 bg-green-500/10 text-green-300',
    in_progress: 'border-primary-600 bg-primary-600/10 text-primary-300',
    pending: 'border-dark-600 bg-dark-800/70 text-dark-200',
    blocked: 'border-red-700 bg-red-600/10 text-red-300'
  };

  const renderAiPlan = (plan) => {
    if (!plan) return null;
    const summary = normalizeChatInput(
      plan.summary || plan.thoughts || plan.description || ''
    );
    const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];

    return (
      <div className="mt-2 bg-dark-800/80 border border-dark-600 rounded-lg p-3 space-y-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-dark-400">
          <Workflow className="w-3.5 h-3.5" />
          <span>AI plan</span>
        </div>
        {summary && <p className="text-sm text-dark-100">{summary}</p>}
        {tasks.length > 0 && (
          <div className="space-y-1">
            {tasks.slice(0, 6).map((task, idx) => {
              const statusKey = String(task.status || 'pending').toLowerCase();
              const badgeClass = planStatusStyles[statusKey] || planStatusStyles.pending;
              const title = normalizeChatInput(
                task.title || task.summary || `Task ${idx + 1}`
              );
              const details =
                task.details != null ? normalizeChatInput(task.details) : '';
              return (
                <div
                  key={task.id || `${task.title || 'task'}-${idx}`}
                  className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-dark-900/60 text-sm text-dark-100"
                >
                  <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${badgeClass}`}>
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

  const handleSendChat = async (message, isComposer = false) => {
    const originalMessage = message;
    const normalizedMessage = normalizeChatInput(message);
    const safeRawContent =
      typeof originalMessage === 'string' ? originalMessage : normalizedMessage;
    if (!normalizedMessage.trim() || isLoadingChat) return;

    const sanitizedHistory = chatMessages
      .filter(msg => msg.role === 'user' || msg.role === 'assistant')
      .map(msg => ({
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp,
      }));

    const modePayload = (agentMode || 'agent').toLowerCase();
    const isAgentLikeMode = modePayload === 'agent' || modePayload === 'plan';
    const shouldEnableComposerMode = isComposer || isAgentLikeMode;

    let finalMessage = normalizedMessage;
    if (activeTab) {
      const activeTag = `@${activeTab}`;
      finalMessage = finalMessage
        .replace(/@current/gi, activeTag)
        .replace(/@active/gi, activeTag)
        .replace(/@file/gi, activeTag);
    }

    // Detect file mentions
    const fileMentions = detectFileMentions(finalMessage);
    const mentionedFiles = [];
    const isNewScriptRequest = detectNewScriptIntent(finalMessage);
    
    // Load content for mentioned files
    for (const mention of fileMentions) {
      // Try to find exact match in open files first
      const exactMatch = openFiles.find(f => 
        f.name === mention || f.path === mention || f.path.endsWith(mention)
      );
      if (exactMatch) {
        mentionedFiles.push(exactMatch);
        continue;
      }
      
      // Try to find in file tree
      const findInTree = (tree, name) => {
        for (const item of tree) {
          if (!item.is_directory && (item.name === name || item.path.endsWith(name) || item.path.includes(name))) {
            return item;
          }
          if (item.children) {
            const found = findInTree(item.children, name);
            if (found) return found;
          }
        }
        return null;
      };
      
      const foundFile = findInTree(fileTree, mention);
      if (foundFile) {
        // Try to load file content if not already loaded
        try {
          const response = await ApiService.readFile(foundFile.path);
          mentionedFiles.push({
            path: foundFile.path,
            name: foundFile.name,
            content: response.content
          });
        } catch (error) {
          // If can't read, just add the file info
          mentionedFiles.push({
            path: foundFile.path,
            name: foundFile.name,
            content: null
          });
        }
      }
    }

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: finalMessage,
      rawContent: safeRawContent,
      timestamp: new Date().toISOString(),
      isComposer: isComposer
    };

    setChatMessages(prev => [...prev, userMessage]);
    if (isComposer) {
      setComposerInput('');
    } else {
      setChatInput('');
    }
    setThinkingAiPlan(null);
    setIsLoadingChat(true);
    setShowFileSuggestions(false);

    // Create abort controller for this request
    const abortController = new AbortController();
    setChatAbortController(abortController);

    try {
      if (!isNewScriptRequest && mentionedFiles.length === 0 && activeTab) {
        const activeFileData = openFiles.find(f => f.path === activeTab);
        if (activeFileData) {
          mentionedFiles.push({
            path: activeFileData.path,
            name: activeFileData.name,
            content: activeFileData.content ? activeFileData.content.substring(0, 5000) : null
          });
        } else {
          mentionedFiles.push({
            path: activeTab,
            name: activeTab.split('/').pop() || activeTab,
            content: null
          });
        }
      }

      // Build comprehensive context
      const activeFileForContext = isNewScriptRequest ? null : activeTab;
      const openFilesForContext = isNewScriptRequest ? [] : openFiles;

      const context = {
        current_page: 'ide',
        mode: modePayload,
        chat_mode: modePayload,
        web_search_mode: webSearchMode,
        default_target_file: activeFileForContext,
        active_file: activeFileForContext,
        active_file_content: activeFileForContext
          ? openFiles.find(f => f.path === activeFileForContext)?.content
          : null,
        open_files: openFilesForContext.map(f => ({
          path: f.path,
          name: f.name,
          content: f.content ? f.content.substring(0, 5000) : null, // Limit content size
          language: f.language,
          is_active: f.path === activeTab
        })),
        mentioned_files: mentionedFiles.map(f => ({
          path: f.path || f,
          name: f.name || f,
          content: f.content ? f.content.substring(0, 5000) : null // Limit content size
        })),
        file_tree_structure: simplifyFileTree(fileTree), // Simplified file tree without full content
        ...(shouldEnableComposerMode && { composer_mode: true })
      };

      if (isNewScriptRequest) {
        context.intent = 'new_script';
        context.requested_new_script = true;
        context.disable_active_file_context = true;
        context.new_script_prompt = finalMessage;
      }

      if (shouldEnableComposerMode) {
        ApiService.previewAgentStatuses(finalMessage, context)
          .then((preview) => {
            if (preview?.agent_statuses?.length) {
              scheduleAgentStatuses(preview.agent_statuses);
            }
          })
          .catch((error) => {
            console.warn('Failed to load agent status preview', error);
          });
      }

      if (shouldEnableComposerMode) {
        ApiService.previewAgentStatuses(finalMessage, context)
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
        finalMessage,
        context,
        sanitizedHistory,
        { mode: modePayload, signal: abortController.signal }
      );
      
      // Debug: inspect raw response payload from backend
      // eslint-disable-next-line no-console
      console.log('IDELayout.handleSendChat: ApiService.sendMessage response', {
        response,
        responseType: typeof response,
        responseResponseType: typeof response?.response,
      });
      
      // Check if request was aborted
      if (abortController.signal.aborted) {
        setIsLoadingChat(false);
        setThinkingAiPlan(null);
        return;
      }

      const assistantPlan = response.ai_plan || null;
      await previewAiPlanBeforeAnswer(assistantPlan);

      const assistantContent = normalizeChatInput(response.response);

      // Debug: inspect assistant content after normalization
      // eslint-disable-next-line no-console
      console.log('IDELayout.handleSendChat: assistantContent after normalizeChatInput', {
        assistantContent,
        assistantContentType: typeof assistantContent,
      });

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: assistantContent,
        rawContent: assistantContent,
        timestamp: response.timestamp,
        plan: assistantPlan
      };

      setChatMessages(prev => [...prev, assistantMessage]);

      if (response.file_operations && response.file_operations.length > 0) {
        const normalizedOperations = coalesceFileOperationsForEditor(
          response.file_operations.map((op) => ({
            ...op,
            path: normalizeEditorPath(op.path),
          }))
        );

        try {
          const operationsWithPreviews = await buildFileOperationPreviews(normalizedOperations);
          setPendingFileOperations({
            operations: operationsWithPreviews,
            assistantMessageId: assistantMessage.id,
            mode: modePayload,
          });
          setActiveFileOperationIndex(0);
          toast.success('Review the AI file changes before deciding to keep them.');
        } catch (error) {
          console.error('Failed to build AI file operation previews:', error);
          // Fall back to showing raw operations without rich previews
          setPendingFileOperations({
            operations: normalizedOperations,
            assistantMessageId: assistantMessage.id,
            mode: modePayload,
          });
          setActiveFileOperationIndex(0);
          toast.error('AI proposed file changes, but previews failed to load. Review carefully before applying.');
        }
      }
      setIsLoadingChat(false);
      setThinkingAiPlan(null);
    } catch (error) {
      if (error.name === 'AbortError' || abortController.signal.aborted) {
        toast('Chat stopped');
      } else {
        console.error('Error sending message:', error);
        toast.error(error.response?.data?.detail || 'Failed to send message');
      }
      setIsLoadingChat(false);
      setThinkingAiPlan(null);
    } finally {
      setChatAbortController(null);
      clearAgentStatuses();
    }
  };

  const handleFollowUpSubmit = async (e) => {
    e.preventDefault();
    if (!followUpInput.trim() || isLoadingChat) return;
    const shouldUseComposer = agentMode !== 'ask';
    await handleSendChat(followUpInput, shouldUseComposer);
    setFollowUpInput('');
  };

  // Clear any inline diff decorations in the editor
  const clearEditorDiffDecorations = useCallback(() => {
    if (!editorRef.current || !monacoRef.current) return;
    editorDiffDecorationsRef.current = editorRef.current.deltaDecorations(
      editorDiffDecorationsRef.current,
      []
    );
  }, []);

  // Process file operations from AI response (writes to disk and updates open files)
  const processFileOperations = async (operations) => {
    for (const op of operations) {
      try {
        const opType = op.type;
        const filePath = normalizeEditorPath(op.path);

        if (opType === 'create_file') {
          const content = op.content || '';
          
          // Create file
          await ApiService.writeFile(filePath, content);
          
          // Open the file if it doesn't exist in openFiles
          if (!openFiles.find(f => f.path === filePath)) {
            const fileInfo = {
              path: filePath,
              name: filePath.split('/').pop() || 'untitled',
              content,
              language: getLanguageFromPath(filePath),
              modified: false
            };
            setOpenFiles(prev => [...prev, fileInfo]);
            setActiveTab(filePath);
            setEditorContent(content);
            setEditorLanguage(fileInfo.language);
          }
          
          toast.success(`Created file: ${filePath}`);
        } else if (opType === 'edit_file') {
          const content = op.content || '';
          
          // Update file
          await ApiService.writeFile(filePath, content);
          
          // Update in openFiles if open
          const fileIndex = openFiles.findIndex(f => f.path === filePath);
          if (fileIndex >= 0) {
            setOpenFiles(prev => prev.map((f, idx) => 
              idx === fileIndex ? { ...f, content, modified: false } : f
            ));
            
            // Update editor if active
            if (activeTab === filePath) {
              setEditorContent(content);
            }
          } else {
            // Open the file
            const fileInfo = {
              path: filePath,
              name: filePath.split('/').pop() || 'untitled',
              content,
              language: getLanguageFromPath(filePath),
              modified: false
            };
            setOpenFiles(prev => [...prev, fileInfo]);
            setActiveTab(filePath);
            setEditorContent(content);
            setEditorLanguage(fileInfo.language);
          }
          
          toast.success(`Updated file: ${filePath}`);
        } else if (opType === 'delete_file') {
          await ApiService.deleteFile(filePath);
          
          // Remove from openFiles if open
          setOpenFiles(prev => prev.filter(f => f.path !== filePath));
          if (activeTab === filePath) {
            const remaining = openFiles.filter(f => f.path !== filePath);
            if (remaining.length > 0) {
              const lastFile = remaining[remaining.length - 1];
              setActiveTab(lastFile.path);
              setEditorContent(lastFile.content);
              setEditorLanguage(lastFile.language);
            } else {
              setActiveTab(null);
              setEditorContent('');
            }
          }
          
          toast.success(`Deleted file: ${filePath}`);
        }
      } catch (error) {
        console.error(`Error processing file operation ${op.type}:`, error);
        toast.error(`Failed to ${op.type} file: ${op.path}`);
      }
    }
    clearEditorDiffDecorations();
    await refreshFileTree();
  };

  // Handle input change with file mention detection
  const handleComposerInputChange = (e) => {
    const value = e.target.value;
    setComposerInput(value);
    setSuggestionInputType('composer');
    
    // Check for @ mention
    const cursorPos = e.target.selectionStart;
    const textBeforeCursor = value.substring(0, cursorPos);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');
    
    if (lastAtIndex !== -1) {
      const query = textBeforeCursor.substring(lastAtIndex + 1).split(/\s/)[0];
      const suggestions = getFileSuggestions(query);
      setFileSuggestions(suggestions);
      setShowFileSuggestions(suggestions.length > 0);
      setMentionPosition({ start: lastAtIndex, end: cursorPos });
    } else {
      setShowFileSuggestions(false);
      setMentionPosition(null);
    }
  };

  const insertFileMention = (file) => {
    if (!mentionPosition) return;
    const mentionValue = typeof file === 'object'
      ? (file.displayPath || file.path || file.name)
      : file;
    
    if (suggestionInputType === 'composer') {
      const before = composerInput.substring(0, mentionPosition.start);
      const after = composerInput.substring(mentionPosition.end);
      const newValue = `${before}@${mentionValue} ${after}`;
      setComposerInput(newValue);
      
      setTimeout(() => {
        composerInputRef.current?.focus();
        const newPos = before.length + mentionValue.length + 2;
        composerInputRef.current?.setSelectionRange(newPos, newPos);
      }, 0);
    } else {
      const before = chatInput.substring(0, mentionPosition.start);
      const after = chatInput.substring(mentionPosition.end);
      const newValue = `${before}@${mentionValue} ${after}`;
      setChatInput(newValue);
      
      setTimeout(() => {
        chatInputRef.current?.focus();
        const newPos = before.length + mentionValue.length + 2;
        chatInputRef.current?.setSelectionRange(newPos, newPos);
      }, 0);
    }
    
    setShowFileSuggestions(false);
    setMentionPosition(null);
  };

  const handleComposerSubmit = async (e) => {
    e.preventDefault();
    setShowFileSuggestions(false);
    await handleSendChat(composerInput, true);
  };

  const openOperationPreview = useCallback(
    (op) => {
      const targetPath = normalizeEditorPath(op.path);
      const afterContent = op.afterContent || op.content || '';

      // Update or create the open file entry with the AI-proposed content
      setOpenFiles((prev) => {
        const existingIndex = prev.findIndex((f) => f.path === targetPath);
        const baseFile = {
          path: targetPath,
          name: targetPath.split('/').pop() || 'untitled',
          content: afterContent,
          language: getLanguageFromPath(targetPath),
          modified: true,
          aiPreview: true,
        };

        if (existingIndex >= 0) {
          const next = [...prev];
          next[existingIndex] = { ...next[existingIndex], ...baseFile };
          return next;
        }
        return [...prev, baseFile];
      });

      setActiveTab(targetPath);
      setEditorContent(afterContent);
      setEditorLanguage(getLanguageFromPath(targetPath));

      if (!editorRef.current || !monacoRef.current || !Array.isArray(op.diff)) {
        return;
      }

      const monaco = monacoRef.current;
      const editor = editorRef.current;
      const model = editor.getModel();
      if (!model) return;

      const decorations = [];

      op.diff.forEach((line) => {
        if (line.type === 'added' && typeof line.newNumber === 'number') {
          const lineNumber = line.newNumber;
          decorations.push({
            range: new monaco.Range(lineNumber, 1, lineNumber, 1),
            options: {
              isWholeLine: true,
              className: 'ai-editor-line-added',
              glyphMarginClassName: 'ai-editor-glyph-added',
              glyphMarginHoverMessage: { value: 'AI: added line' },
            },
          });
        }
      });

      editorDiffDecorationsRef.current = editor.deltaDecorations(
        editorDiffDecorationsRef.current,
        decorations
      );
    },
    [getLanguageFromPath, setOpenFiles]
  );

  const handleApplyPendingFileOperations = async () => {
    if (!pendingFileOperations) return;
    try {
      setIsApplyingFileOperations(true);
      await processFileOperations(pendingFileOperations.operations);
      toast.success('Applied AI changes');
    } catch (error) {
      console.error('Failed to apply AI changes:', error);
      toast.error('Failed to apply AI changes');
    } finally {
      setIsApplyingFileOperations(false);
      setPendingFileOperations(null);
      setActiveFileOperationIndex(0);
    }
  };

  const handleDiscardPendingFileOperations = async () => {
    if (!pendingFileOperations || !pendingFileOperations.operations) {
      setPendingFileOperations(null);
      setActiveFileOperationIndex(0);
      toast('Dismissed AI changes');
      return;
    }

    try {
      setIsApplyingFileOperations(true);

      // If we created any files on disk during preview, clean them up
      const createdPaths = pendingFileOperations.operations
        .filter((op) => op.type === 'create_file' && op.previewCreated)
        .map((op) => normalizeEditorPath(op.path));

      if (createdPaths.length > 0) {
        for (const filePath of createdPaths) {
          try {
            await ApiService.deleteFile(filePath);
          } catch (error) {
            // eslint-disable-next-line no-console
            console.warn('Failed to delete preview file on discard:', filePath, error);
          }
        }

        // Remove any preview-created files from open tabs
        setOpenFiles((prev) => prev.filter((file) => !createdPaths.includes(file.path)));

        // Adjust activeTab/editor if the active file was removed
        setActiveTab((currentActive) => {
          if (!currentActive || !createdPaths.includes(currentActive)) {
            return currentActive;
          }
          const remaining = openFiles.filter((f) => !createdPaths.includes(f.path));
          if (remaining.length > 0) {
            const lastFile = remaining[remaining.length - 1];
            setEditorContent(lastFile.content);
            setEditorLanguage(lastFile.language);
            return lastFile.path;
          }
          setEditorContent('');
          return null;
        });

        await refreshFileTree();
      }
    } finally {
      setIsApplyingFileOperations(false);
      setPendingFileOperations(null);
      setActiveFileOperationIndex(0);
      toast('Dismissed AI changes');
    }
  };

  // When reviewing changes, automatically open the currently selected operation
  // in the editor so the user can immediately see the proposed code.
  useEffect(() => {
    if (!pendingFileOperations || !pendingFileOperations.operations?.length) {
      return;
    }

    const operations = pendingFileOperations.operations;
    const totalOps = operations.length;
    const index = Math.min(
      Math.max(activeFileOperationIndex, 0),
      Math.max(totalOps - 1, 0)
    );
    const op = operations[index];

    if (!op) return;
    openOperationPreview(op);
  }, [pendingFileOperations, activeFileOperationIndex, openOperationPreview]);

  const closeTab = (filePath, e) => {
    e.stopPropagation();
    const newOpenFiles = openFiles.filter(f => f.path !== filePath);
    setOpenFiles(newOpenFiles);

    if (selectedFile === filePath) {
      const fallback = newOpenFiles.length > 0 ? newOpenFiles[newOpenFiles.length - 1].path : null;
      setSelectedFile(fallback);
    }
    
    if (activeTab === filePath) {
      if (newOpenFiles.length > 0) {
        const lastFile = newOpenFiles[newOpenFiles.length - 1];
        setActiveTab(lastFile.path);
        setEditorContent(lastFile.content);
        setEditorLanguage(lastFile.language);
      } else {
        setActiveTab(null);
        setEditorContent('');
      }
    }
  };

  const renderFileTree = (fileList, depth = 0) => {
    if (!fileList || fileList.length === 0) return null;

    return (
      <>
        {fileList.map((file) => {
          if (file.is_directory) {
            const isExpanded = expandedFolders.has(file.path);
            const hasChildren = file.children && file.children.length > 0;
            const canExpand = hasChildren || file.has_more_children;
            
            return (
              <div key={file.path}>
                <div
                  className="flex items-center px-2 py-1 hover:bg-dark-700 cursor-pointer text-sm"
                  style={{ paddingLeft: `${8 + depth * 16}px` }}
                  onClick={(e) => handleFileClick(file, e)}
                  onContextMenu={(e) => handleFileContextMenu(e, file)}
                >
                  {canExpand ? (
                    isExpanded ? (
                      <ChevronDown className="w-4 h-4 mr-1 text-dark-400 flex-shrink-0" />
                    ) : (
                      <ChevronRightIcon className="w-4 h-4 mr-1 text-dark-400 flex-shrink-0" />
                    )
                  ) : (
                    <div className="w-4 h-4 mr-1" />
                  )}
                  <Folder className="w-4 h-4 mr-1 text-blue-400 flex-shrink-0" />
                  <span className="text-dark-200 truncate">{file.name}</span>
                  {file.has_more_children && (
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-dark-500">partial</span>
                  )}
                </div>
                {isExpanded && hasChildren && renderFileTree(file.children, depth + 1)}
              </div>
            );
          } else {
            return (
                <div
                  key={file.path}
                  className={`flex items-center px-2 py-1 hover:bg-dark-700 cursor-pointer text-sm ${
                    selectedFile === file.path ? 'bg-dark-700' : ''
                  }`}
                  style={{ paddingLeft: `${8 + depth * 16}px` }}
                  onClick={(e) => handleFileClick(file, e)}
                  onContextMenu={(e) => handleFileContextMenu(e, file)}
                >
                <div className="w-4 h-4 mr-1 flex-shrink-0" />
                <File className="w-4 h-4 mr-1 text-dark-400 flex-shrink-0" />
                <span className="text-dark-200 truncate">{file.name}</span>
              </div>
            );
          }
        })}
      </>
    );
  };

  return (
    <div className="flex flex-col h-screen bg-dark-900 text-dark-100 overflow-hidden">
      {/* Top Menu Bar */}
      <div className="h-10 bg-dark-800 border-b border-dark-700 flex items-center px-4 text-sm">
        <div className="flex items-center space-x-4">
          <button className="hover:bg-dark-700 px-2 py-1 rounded">Agents</button>
          <button className="hover:bg-dark-700 px-2 py-1 rounded">Editor</button>
          <MenuDropdown label="File" items={fileMenuItems} />
          <MenuDropdown label="Edit" items={editMenuItems} />
          <MenuDropdown label="Selection" items={selectionMenuItems} />
          <MenuDropdown label="View" items={viewMenuItems} />
          <MenuDropdown label="Go" items={goMenuItems} />
          <MenuDropdown label="Run" items={runMenuItems} />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <input
            ref={searchInputRef}
            type="text"
            placeholder={`Search ${projectRoot.name}`}
            className="bg-dark-700 border border-dark-600 rounded px-3 py-1 text-sm w-64 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        <div className="flex items-center space-x-3 text-xs">
          <div className="text-right">
            <div className="flex items-center gap-1">
              {chatStatus?.ollama_connected ? (
                <Wifi className="w-4 h-4 text-green-500" />
              ) : (
                <WifiOff className="w-4 h-4 text-red-500" />
              )}
              <span className="text-dark-200">
                {chatStatus?.ollama_connected ? 'Ollama connected' : 'Ollama offline'}
              </span>
            </div>
            <div className="text-[10px] text-dark-500">
              {isLoadingStatus ? 'Checking status…' : `Model: ${chatStatus?.current_model || '—'}`}
            </div>
          </div>
          <button
            onClick={() => {
              setShowConnectivityPanel(true);
              loadConnectivitySettings();
            }}
            className="px-3 py-1 rounded-full border border-dark-600 text-dark-200 hover:bg-dark-700 text-[11px]"
          >
            Connectivity Settings
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - File Explorer */}
        {leftSidebarVisible && (
          <>
            <div 
              className="bg-dark-800 border-r border-dark-700 flex flex-col"
              style={{ width: `${leftSidebarWidth}px`, minWidth: '200px', maxWidth: '600px' }}
            >
            <div className="p-3 border-b border-dark-700">
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-semibold text-dark-200 truncate">{projectRoot.name}</h3>
                    <div className="flex items-center gap-1 text-dark-400">
                      <button
                        type="button"
                        onClick={handleCreateFile}
                        className="p-1 rounded hover:bg-dark-700 hover:text-dark-100 transition-colors"
                        title="New File"
                        aria-label="New File"
                      >
                        <FilePlus className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={handleCreateFolder}
                        className="p-1 rounded hover:bg-dark-700 hover:text-dark-100 transition-colors"
                        title="New Folder"
                        aria-label="New Folder"
                      >
                        <FolderPlus className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={handleRefreshExplorer}
                        className="p-1 rounded hover:bg-dark-700 hover:text-dark-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Refresh Explorer"
                        aria-label="Refresh Explorer"
                        disabled={isFileTreeLoading}
                      >
                        {isFileTreeLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <RefreshCw className="w-4 h-4" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={handleCollapseExplorer}
                        className="p-1 rounded hover:bg-dark-700 hover:text-dark-100 transition-colors"
                        title="Collapse folders"
                        aria-label="Collapse folders"
                      >
                        <Minimize2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                  <button
                    onClick={() => setLeftSidebarVisible(false)}
                    className="p-1 hover:bg-dark-700 rounded transition-colors"
                    title="Hide sidebar (Ctrl+B)"
                  >
                    <X className="w-4 h-4 text-dark-400" />
                  </button>
                </div>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {isFileTreeLoading ? (
                <div className="text-xs text-dark-400 p-2">Loading files...</div>
              ) : fileTree.length > 0 ? (
                renderFileTree(fileTree)
              ) : (
                <div className="text-xs text-dark-400 p-2">No files found</div>
              )}
            </div>
            {folderSearchResults && (
              <div className="border-t border-dark-700 p-2 text-xs text-dark-300 space-y-2 bg-dark-900/60">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-dark-100 font-semibold">
                      Search “{folderSearchResults.query}”
                    </div>
                    <div className="text-[10px] text-dark-500">
                      {formatDisplayPath(folderSearchResults.folderPath)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFolderSearchResults(null)}
                    className="text-[10px] uppercase tracking-wide text-dark-400 hover:text-dark-100"
                  >
                    Clear
                  </button>
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {folderSearchResults.results.length > 0 ? (
                    folderSearchResults.results.map((result) => (
                      <button
                        key={result.path}
                        type="button"
                        onClick={() => loadFile(result.path)}
                        className="w-full text-left px-2 py-1 rounded hover:bg-dark-700 flex items-center gap-2"
                      >
                        <File className="w-3 h-3 text-dark-500" />
                        <div className="flex-1">
                          <div className="text-dark-100 text-xs">{result.name}</div>
                          <div className="text-[10px] text-dark-500 truncate">
                            {formatDisplayPath(result.path)}
                          </div>
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="text-[11px] text-dark-500">No matches found.</div>
                  )}
                </div>
              </div>
            )}
            <div className="p-2 border-t border-dark-700 text-xs text-dark-400">
              <div>OUTLINE</div>
              <div className="mt-1">TIMELINE</div>
              <div className="mt-2 pt-2 border-t border-dark-700">
                <div>main</div>
                <div>0 changes</div>
              </div>
            </div>
            </div>
            {/* Left Resize Handle */}
            <div
              onMouseDown={() => setIsResizingLeft(true)}
              className="w-1 bg-dark-700 hover:bg-primary-500 cursor-col-resize transition-colors"
              style={{ minWidth: '4px' }}
              title="Drag to resize"
            />
          </>
        )}

        {/* Center - Editor Area */}
        <div className="flex-1 flex flex-col bg-dark-900">
          {/* Editor Tabs */}
          {openFiles.length > 0 && (
            <div className="flex bg-dark-800 border-b border-dark-700 overflow-x-auto">
              {openFiles.map((file) => (
                <div
                  key={file.path}
                  className={`flex items-center px-3 py-2 border-r border-dark-700 cursor-pointer text-sm ${
                    activeTab === file.path ? 'bg-dark-900' : 'bg-dark-800 hover:bg-dark-750'
                  }`}
                  onClick={() => {
                    setActiveTab(file.path);
                    setEditorContent(file.content);
                    setEditorLanguage(file.language);
                  }}
                >
                  <File className="w-3 h-3 mr-2 text-dark-400" />
                  <span className="text-dark-200">{file.name}</span>
                  {file.modified && (
                    <span className="ml-1 w-2 h-2 bg-primary-500 rounded-full" title="Modified" />
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (file.modified) {
                        if (window.confirm(`${file.name} has unsaved changes. Save before closing?`)) {
                          saveFile(file.path);
                        }
                      }
                      closeTab(file.path, e);
                    }}
                    className="ml-2 hover:bg-dark-700 rounded p-0.5"
                    title="Close tab"
                  >
                    <X className="w-3 h-3 text-dark-400" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {pendingFileOperations && (() => {
            const operations = pendingFileOperations.operations || [];
            const totalOps = operations.length;
            if (totalOps === 0) return null;

            const clampedIndex = Math.min(
              Math.max(activeFileOperationIndex, 0),
              Math.max(totalOps - 1, 0)
            );
            const op = operations[clampedIndex];
            const normalizedPath = normalizeEditorPath(op.path);
            const isActive = activeTab === normalizedPath;

            const goPrev = () => {
              setActiveFileOperationIndex((prev) => (prev > 0 ? prev - 1 : prev));
            };

            const goNext = () => {
              setActiveFileOperationIndex((prev) =>
                prev < totalOps - 1 ? prev + 1 : prev
              );
            };

            return (
              <div className="border-b border-primary-700/40 bg-primary-900/10 text-sm p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <h4 className="text-dark-100 font-semibold">Review AI changes</h4>
                    <p className="text-xs text-dark-300">
                      Change {clampedIndex + 1} of {totalOps} •{' '}
                      {pendingFileOperations.mode?.toUpperCase() || 'AI'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1 text-xs text-dark-300">
                      <button
                        type="button"
                        onClick={goPrev}
                        disabled={clampedIndex === 0}
                        className="p-1 rounded border border-dark-600 hover:bg-dark-800 disabled:opacity-40"
                        aria-label="Previous change"
                      >
                        <ChevronLeft className="w-3 h-3" />
                      </button>
                      <span className="min-w-[42px] text-center">
                        {clampedIndex + 1} / {totalOps}
                      </span>
                      <button
                        type="button"
                        onClick={goNext}
                        disabled={clampedIndex >= totalOps - 1}
                        className="p-1 rounded border border-dark-600 hover:bg-dark-800 disabled:opacity-40"
                        aria-label="Next change"
                      >
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={handleDiscardPendingFileOperations}
                        disabled={isApplyingFileOperations}
                        className="px-3 py-1.5 rounded-lg border border-dark-600 text-dark-200 text-xs hover:bg-dark-800 disabled:opacity-60"
                      >
                        Undo All
                      </button>
                      <button
                        type="button"
                        onClick={handleApplyPendingFileOperations}
                        disabled={isApplyingFileOperations}
                        className="px-3 py-1.5 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs disabled:opacity-60"
                      >
                        {isApplyingFileOperations ? 'Applying…' : 'Keep All'}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-2 flex items-center justify-between text-xs text-dark-300">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-dark-800 text-primary-400 uppercase text-[10px]">
                      {op.type.replace('_', ' ')}
                    </span>
                    <span className="text-dark-200 truncate max-w-[320px]">
                      {normalizedPath}
                    </span>
                  </div>
                  <span className="text-[11px] text-dark-500">
                    File below shows this change with highlighted lines.
                  </span>
                </div>
              </div>
            );
          })()}

          {/* Editor Content */}
          <div className="flex-1 relative">
            {activeTab ? (
              <Editor
                height="100%"
                language={editorLanguage}
                value={editorContent}
                onMount={(editorInstance, monacoInstance) => {
                  editorRef.current = editorInstance;
                  monacoRef.current = monacoInstance;
                  setIsEditorReady(true);
                }}
                onChange={(value) => {
                  const newContent = value || '';
                  setEditorContent(newContent);
                  // Update content in openFiles and mark as modified
                  setOpenFiles(prev => prev.map(f => 
                    f.path === activeTab ? { ...f, content: newContent, modified: true } : f
                  ));
                }}
                theme="vs-dark"
                options={editorOptions}
              />
            ) : (
              <div className="flex items-center justify-center h-full bg-dark-900">
                <div className="text-center max-w-2xl">
                  <div className="w-32 h-32 mx-auto mb-6 bg-gradient-to-br from-primary-500 via-primary-600 to-primary-700 rounded-2xl flex items-center justify-center shadow-2xl shadow-primary-500/20">
                    <div className="w-20 h-20 bg-dark-900/30 rounded-xl flex items-center justify-center">
                      <Code2 className="w-12 h-12 text-white" />
                    </div>
                  </div>
                  <h2 className="text-2xl font-bold text-dark-100 mb-8">Welcome to AI Agent</h2>
                  <div className="space-y-3 text-sm text-dark-300">
                    <div className="grid grid-cols-2 gap-4 mb-6">
                      <div className="flex items-center justify-between p-3 bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-750 transition-colors">
                        <span className="text-dark-300">New Agent</span>
                        <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded text-xs font-mono">Ctrl + Shift + L</kbd>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-750 transition-colors">
                        <span className="text-dark-300">Hide Terminal</span>
                        <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded text-xs font-mono">Ctrl + J</kbd>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-750 transition-colors">
                        <span className="text-dark-300">Hide Files</span>
                        <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded text-xs font-mono">Ctrl + B</kbd>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-dark-800 border border-dark-700 rounded-lg hover:bg-dark-750 transition-colors">
                        <span className="text-dark-300">Search Files</span>
                        <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded text-xs font-mono">Ctrl + P</kbd>
                      </div>
                    </div>
                    <div className="flex items-center justify-center p-3 bg-dark-800 border border-dark-700 rounded-lg">
                      <span className="text-dark-300 mr-3">Open Browser</span>
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded text-xs font-mono">Ctrl + Shift + B</kbd>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Sidebar - AI Chat */}
        {rightSidebarVisible && (
          <>
            {/* Right Resize Handle */}
            <div
              onMouseDown={() => setIsResizingRight(true)}
              className="w-1 bg-dark-700 hover:bg-primary-500 cursor-col-resize transition-colors"
              style={{ minWidth: '4px' }}
              title="Drag to resize"
            />
            <div 
              className="bg-dark-800 border-l border-dark-700 flex flex-col h-full"
              style={{ width: `${rightSidebarWidth}px`, minWidth: '200px', maxWidth: '600px' }}
            >
            {/* Chat Tabs */}
            <div className="flex items-center border-b border-dark-700 bg-dark-800">
              {chatTabs.map((tab) => (
                <div
                  key={tab.id}
                  className={`flex items-center gap-2 px-3 py-2 border-r border-dark-700 cursor-pointer text-sm ${
                    activeChatTab === tab.id
                      ? 'bg-dark-900 text-dark-100'
                      : 'bg-dark-800 text-dark-400 hover:text-dark-200'
                  }`}
                  onClick={() => setActiveChatTab(tab.id)}
                >
                  <span className="truncate max-w-[120px]">{tab.title}</span>
                  {chatTabs.length > 1 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (chatTabs.length > 1) {
                          const newTabs = chatTabs.filter(t => t.id !== tab.id);
                          setChatTabs(newTabs);
                          if (activeChatTab === tab.id && newTabs.length > 0) {
                            setActiveChatTab(newTabs[0].id);
                          }
                        }
                      }}
                      className="hover:bg-dark-700 rounded p-0.5"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              ))}
              <div className="flex-1 flex items-center justify-end gap-1 px-2">
                <button
                  type="button"
                  onClick={() => {
                    const newId = Math.max(...chatTabs.map(t => t.id), 0) + 1;
                    setChatTabs(prev => prev.map(t => ({ ...t, isActive: false })).concat([{ id: newId, title: 'New Chat', isActive: true }]));
                    setActiveChatTab(newId);
                    setChatMessages([]);
                  }}
                  className="p-1.5 hover:bg-dark-700 rounded transition-colors"
                  title="New Chat"
                >
                  <Plus className="w-4 h-4 text-dark-400" />
                </button>
                <button
                  type="button"
                  className="p-1.5 hover:bg-dark-700 rounded transition-colors"
                  title="History"
                >
                  <Clock className="w-4 h-4 text-dark-400" />
                </button>
                <button
                  type="button"
                  className="p-1.5 hover:bg-dark-700 rounded transition-colors"
                  title="More"
                >
                  <MoreVertical className="w-4 h-4 text-dark-400" />
                </button>
              </div>
            </div>

            {/* Top Header - File Count and Stop Button */}
            <div className="px-3 py-2 border-b border-dark-700 bg-dark-700/50 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-dark-400">
                <ChevronRightIcon className="w-3 h-3" />
                <span>{openFiles.length} File{openFiles.length !== 1 ? 's' : ''}</span>
              </div>
              {isLoadingChat && (
                <button
                  type="button"
                  className="flex items-center gap-2 px-2 py-1 text-xs text-dark-300 hover:bg-dark-600 rounded transition-colors"
                  onClick={handleStopChat}
                >
                  <span>Stop</span>
                  <kbd className="px-1 py-0.5 bg-dark-700 border border-dark-600 rounded text-[10px] font-mono">Ctrl+Shift+X</kbd>
                  <Square className="w-3 h-3 fill-current" />
                </button>
              )}
            </div>
            
            {/* Main Composer Input Area */}
            <div className="p-3 border-b border-dark-700 bg-dark-800">
              <form onSubmit={handleComposerSubmit} className="relative">
                <div className="flex items-start gap-2 mb-3">
                  <textarea
                    ref={composerInputRef}
                    value={composerInput}
                    onChange={handleComposerInputChange}
                    placeholder="Plan, @ for context, / for commands"
                    rows={1}
                    className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-1 focus:ring-primary-500 text-sm resize-none min-h-[38px] max-h-32 overflow-y-auto"
                    disabled={isLoadingChat}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleComposerSubmit(e);
                      } else if (e.key === 'Escape') {
                        setShowFileSuggestions(false);
                      } else if (e.key === 'ArrowDown' && showFileSuggestions && fileSuggestions.length > 0) {
                        e.preventDefault();
                      }
                    }}
                    onInput={(e) => {
                      // Auto-resize textarea based on content
                      e.target.style.height = 'auto';
                      e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px';
                    }}
                  />
                </div>
                {showFileSuggestions && fileSuggestions.length > 0 && suggestionInputType === 'composer' && (
                  <div className="file-suggestions-container absolute top-full left-0 right-0 mt-2 w-full bg-dark-800 border border-dark-600 rounded-lg shadow-lg z-50 max-h-60 overflow-y-auto">
                    {fileSuggestions.map((file, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => insertFileMention(file)}
                        className="w-full text-left px-3 py-2 text-sm text-dark-300 hover:bg-dark-700 flex items-center space-x-2"
                      >
                        <File className="w-4 h-4 text-dark-400" />
                        <div className="flex-1">
                          <div className="font-medium">{file.name}</div>
                          <div className="text-xs text-dark-500 truncate">{file.displayPath}</div>
                        </div>
                        {file.isOpen && (
                          <span className="text-xs text-primary-500">Open</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                
                {/* Dropdown Menus */}
                <div className="flex flex-wrap items-center gap-2 mt-3">
                <div className="relative" ref={agentModeMenuRef}>
                  <button
                    type="button"
                    onClick={() => {
                      setShowAgentModeMenu(prev => !prev);
                      setShowAutoDropdown(false);
                      setShowWebSearchMenu(false);
                    }}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-dark-300 hover:bg-dark-700 rounded transition-colors"
                  >
                    <Infinity className="w-3 h-3" />
                    <span>{selectedChatMode.label}</span>
                    <ChevronDown className={`w-3 h-3 transition-transform ${showAgentModeMenu ? 'rotate-180' : ''}`} />
                  </button>
                  {showAgentModeMenu && (
                    <div className="absolute top-full left-0 mt-1 bg-dark-800 border border-dark-700 rounded shadow-lg z-50 min-w-[180px]">
                      {chatModeOptions.map(mode => (
                        <button
                          key={mode.id}
                          type="button"
                          onClick={() => {
                            setAgentMode(mode.id);
                            setShowAgentModeMenu(false);
                          }}
                          className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                            agentMode === mode.id
                              ? 'bg-primary-600 text-white'
                              : 'text-dark-300 hover:bg-dark-700'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span>{mode.label}</span>
                            {agentMode === mode.id && <CheckCircle className="w-3 h-3" />}
                          </div>
                          <p className="text-[10px] text-dark-500 mt-1">{mode.description}</p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1 rounded-lg border border-dark-600 bg-dark-700/40 px-2 py-1 text-dark-400">
                  <button 
                    type="button"
                    onClick={() => {
                      setComposerInput(prev => prev + '@');
                      if (composerInputRef.current) {
                        composerInputRef.current.focus();
                      }
                      setShowWebSearchMenu(false);
                    }}
                    className="hover:text-dark-200 transition-colors"
                    title="Mention"
                  >
                    <AtSign className="w-4 h-4" />
                  </button>
                  <div className="relative" ref={webSearchMenuRef}>
                    <button
                      type="button"
                      onClick={() => {
                        setShowWebSearchMenu(prev => !prev);
                        setShowAgentModeMenu(false);
                        setShowAutoDropdown(false);
                      }}
                      className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors ${
                        showWebSearchMenu ? 'bg-dark-600 text-dark-100' : 'hover:text-dark-200'
                      }`}
                      title={`Web Search (${selectedWebSearchMode.label})`}
                    >
                      <Globe className="w-4 h-4" />
                      <span className="text-[10px] uppercase tracking-wide">{selectedWebSearchMode.label}</span>
                      <ChevronDown className="w-3 h-3" />
                    </button>
                    {showWebSearchMenu && (
                      <div className="absolute top-full left-0 mt-1 bg-dark-800 border border-dark-700 rounded shadow-lg z-50 min-w-[200px]">
                        {webSearchOptions.map((option) => (
                          <button
                            key={option.id}
                            type="button"
                            onClick={() => {
                              setWebSearchMode(option.id);
                              setShowWebSearchMenu(false);
                            }}
                            className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                              webSearchMode === option.id
                                ? 'bg-primary-600 text-white'
                                : 'text-dark-300 hover:bg-dark-700'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span>{option.label}</span>
                              {webSearchMode === option.id && <CheckCircle className="w-3 h-3" />}
                            </div>
                            <p className="text-[10px] text-dark-500 mt-1">{option.description}</p>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="hover:text-dark-200 transition-colors"
                    title="Upload Image"
                  >
                    <Image className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    className="hover:text-dark-200 transition-colors"
                    title="Voice Input"
                  >
                    <Mic className="w-4 h-4" />
                  </button>
                </div>
                <div className="relative group" data-auto-dropdown>
                  <button
                    type="button"
                    onClick={() => {
                      setShowAutoDropdown(!showAutoDropdown);
                      if (!showAutoDropdown && ollamaModels.length === 0) {
                        loadAvailableModels();
                      }
                      setShowAgentModeMenu(false);
                      setShowWebSearchMenu(false);
                    }}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-dark-300 hover:bg-dark-700 rounded transition-colors"
                  >
                    <span>{currentModel || 'Auto'}</span>
                    <ChevronDown className={`w-3 h-3 transition-transform ${showAutoDropdown ? 'rotate-180' : ''}`} />
                  </button>
                  {showAutoDropdown && (
                    <div className="absolute top-full left-0 mt-1 bg-dark-800 border border-dark-700 rounded shadow-lg z-50 min-w-[200px] max-h-64 overflow-y-auto" data-auto-dropdown>
                      {isLoadingModels ? (
                        <div className="px-3 py-2 text-xs text-dark-400 flex items-center gap-2">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Loading models...
                        </div>
                      ) : ollamaModels.length === 0 ? (
                        <div className="px-3 py-2 text-xs text-dark-400">
                          No models available
                        </div>
                      ) : (
                        ollamaModels.map((model) => (
                          <button
                            key={model}
                            type="button"
                            onClick={() => handleSelectModel(model)}
                            className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                              currentModel === model
                                ? 'bg-primary-600 text-white'
                                : 'text-dark-300 hover:bg-dark-700'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span>{model}</span>
                              {currentModel === model && (
                                <CheckCircle className="w-3 h-3" />
                              )}
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
                <div className="relative group">
                  <button
                    type="button"
                    className="flex items-center gap-1 px-2 py-1 text-xs text-dark-300 hover:bg-dark-700 rounded transition-colors"
                  >
                    <Folder className="w-3 h-3" />
                    <span>Local</span>
                    <ChevronDown className="w-3 h-3" />
                  </button>
                </div>
              </div>
              </form>
            </div>

            {/* Chat Messages */}
            <div className="flex-1 overflow-y-auto bg-dark-900 chat-messages-container min-h-0">
              {chatMessages.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <p className="text-sm text-dark-400">Start a conversation with AI</p>
                </div>
              ) : (
                <div className="p-3 space-y-3">
                  {chatMessages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex space-x-2 ${
                        message.role === 'user' ? 'justify-end' : 'justify-start'
                      }`}
                    >
                      {/* Debug: log each message as it is rendered in the IDE chat */}
                      {(() => {
                        // eslint-disable-next-line no-console
                        console.log('IDELayout render chat message bubble', {
                          id: message.id,
                          role: message.role,
                          content: message.content,
                          rawContent: message.rawContent,
                          contentType: typeof message.content,
                          rawContentType: typeof message.rawContent,
                        });
                        return null;
                      })()}
                      {message.role === 'assistant' && (
                        <Bot className="w-5 h-5 text-primary-500 mt-1 flex-shrink-0" />
                      )}
                    {(() => {
                      const normalizedContent = normalizeChatInput(
                        message.rawContent ?? message.content
                      );
                      const formattedHtml = formatMessageContent(normalizedContent);
                      // eslint-disable-next-line no-console
                      console.log('IDELayout render formatted HTML', {
                        id: message.id,
                        role: message.role,
                        normalizedContent,
                        formattedHtml,
                        formattedHtmlType: typeof formattedHtml,
                      });
                      return (
                        <div
                          className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                            message.role === 'user'
                              ? 'bg-primary-600 text-white'
                              : 'bg-dark-700 text-dark-200'
                          }`}
                        >
                          <div
                            className="prose prose-invert max-w-none"
                            dangerouslySetInnerHTML={{
                              __html: formattedHtml,
                            }}
                          />
                          {message.plan &&
                            message.role === 'assistant' &&
                            renderAiPlan(message.plan)}
                        </div>
                      );
                    })()}
                      {message.role === 'user' && (
                        <User className="w-5 h-5 text-dark-400 mt-1 flex-shrink-0" />
                      )}
                    </div>
                  ))}
                  {isLoadingChat && (
                    <div className="flex space-x-2">
                      <Bot className="w-5 h-5 text-primary-500 mt-1" />
                      <div className="bg-dark-700 px-3 py-2 rounded-lg">
                        <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
                        {agentStatuses.length > 0 && (
                          <div className="mt-2 space-y-1 text-xs text-dark-300">
                            {agentStatuses.map((status) => (
                              <div key={status.key} className="flex items-center gap-2">
                                <Loader2 className="w-3 h-3 animate-spin text-primary-500" />
                                <span>{status.label}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {thinkingAiPlan && (
                          <div className="mt-3 border-t border-dark-600 pt-3">
                            {renderAiPlan(thinkingAiPlan)}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Follow-up Input */}
            {chatMessages.length > 0 && (
              <div className="border-t border-dark-700 bg-dark-800 p-3 flex-shrink-0">
                <form onSubmit={handleFollowUpSubmit} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={followUpInput}
                    onChange={(e) => setFollowUpInput(e.target.value)}
                    placeholder="Add a follow-up"
                    className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-1 focus:ring-primary-500 text-sm"
                    disabled={isLoadingChat}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleFollowUpSubmit(e);
                      } else if (e.key === 'Escape') {
                        setShowFileSuggestions(false);
                      }
                    }}
                  />
                  <button
                    type="submit"
                    disabled={!followUpInput.trim() || isLoadingChat}
                    className="p-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    title="Send follow-up"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </form>
              </div>
            )}

            {/* Past Chats */}
            <div className="border-t border-dark-700 bg-dark-800 flex-shrink-0">
              <div 
                className="flex items-center justify-between p-3 cursor-pointer hover:bg-dark-700 transition-colors"
                onClick={() => setShowPastChats(!showPastChats)}
              >
                <div className="flex items-center gap-2">
                  <ChevronDown 
                    className={`w-4 h-4 text-dark-400 transition-transform ${showPastChats ? '' : '-rotate-90'}`}
                  />
                  <h4 className="text-xs font-semibold text-dark-400">Past Chats</h4>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    // Handle View All action
                  }}
                  className="text-xs text-dark-500 hover:text-dark-300 transition-colors"
                >
                  View All
                </button>
              </div>
              {showPastChats && (
                <div className="px-3 pb-3 space-y-1">
                  {pastChats.map((chat) => (
                    <div
                      key={chat.id}
                      className="text-xs text-dark-400 hover:text-dark-200 cursor-pointer py-1 px-2 hover:bg-dark-700 rounded transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="truncate flex-1">{chat.title}</span>
                        <span className="ml-2 text-dark-500 text-[10px] whitespace-nowrap">{chat.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            </div>
          </>
        )}
      </div>

      {/* Bottom Panel - Terminal */}
      {bottomPanelVisible && (
        <>
          <div 
            className="bg-dark-800 border-t border-dark-700 flex flex-col"
            style={{ height: `${bottomPanelHeight}px`, minHeight: '150px', maxHeight: '600px' }}
          >
          <div className="flex items-center border-b border-dark-700">
            {['problems', 'output', 'debug console', 'terminal', 'ports'].map((tab) => (
              <button
                key={tab}
                onClick={() => setBottomPanelTab(tab)}
                className={`px-4 py-2 text-sm border-r border-dark-700 ${
                  bottomPanelTab === tab
                    ? 'bg-dark-900 text-dark-100'
                    : 'bg-dark-800 text-dark-400 hover:text-dark-200'
                }`}
              >
                {tab}
              </button>
            ))}
            <div className="flex-1"></div>
            <button
              onClick={() => setBottomPanelVisible(false)}
              className="px-2 py-1 hover:bg-dark-700 transition-colors"
              title="Hide panel (Ctrl+J)"
            >
              <X className="w-4 h-4 text-dark-400" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 font-mono text-sm bg-dark-900">
            {bottomPanelTab === 'terminal' && (
              <div className="space-y-2">
                <div className="text-dark-400 mb-2 flex items-center justify-between">
                  <span>{terminalCwd}&gt;</span>
                  {terminalSessionId && (
                    <span className="text-xs text-dark-500">Session: {terminalSessionId.slice(0, 8)}</span>
                  )}
                </div>
                <div className="text-dark-300 text-xs flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>Shortcuts:</span>
                    <span className="flex items-center gap-1">
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded">Ctrl+K</kbd>
                      <span>ask AI</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded">Tab</kbd>
                      <span>complete</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded">↑</kbd>
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded">↓</kbd>
                      <span>history</span>
                    </span>
                    <span className="flex items-center gap-1">
                      <kbd className="px-2 py-1 bg-dark-700 border border-dark-600 rounded">Ctrl+L</kbd>
                      <span>clear</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleHistoryPanelToggle}
                      className={`flex items-center gap-1 px-2 py-1 rounded border text-xs transition-colors ${
                        showHistoryPanel
                          ? 'border-primary-500/60 text-primary-300 bg-primary-500/10'
                          : 'border-dark-600 text-dark-300 hover:text-dark-100'
                      }`}
                    >
                      <History className="w-3 h-3" />
                      History
                    </button>
                    <button
                      type="button"
                      onClick={handleClearTerminalOutput}
                      className="flex items-center gap-1 px-2 py-1 rounded border text-xs border-dark-600 text-dark-300 hover:text-dark-100 transition-colors"
                      title="Clear output (Ctrl+L)"
                    >
                      <Trash2 className="w-3 h-3" />
                      Clear
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-dark-400">
                  <span>Quick:</span>
                  {QUICK_TERMINAL_COMMANDS.map((cmd) => (
                    <button
                      key={cmd}
                      type="button"
                      onClick={() => handleQuickCommand(cmd)}
                      className="px-2 py-1 rounded border border-dark-600 text-dark-300 hover:text-dark-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      disabled={isTerminalBusy}
                    >
                      {cmd}
                    </button>
                  ))}
                </div>
                {showHistoryPanel && (
                  <div className="bg-dark-800 border border-dark-700 rounded-md p-3 text-xs space-y-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={historyFilter}
                        onChange={handleHistoryFilterChange}
                        placeholder="Filter history..."
                        className="flex-1 bg-dark-900 border border-dark-600 rounded px-2 py-1 focus:border-primary-500 outline-none"
                      />
                      <button
                        type="button"
                        onClick={handleClearTerminalHistory}
                        className="flex items-center gap-1 px-2 py-1 rounded border border-dark-600 text-dark-300 hover:text-dark-100 transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                        Clear history
                      </button>
                    </div>
                    <div className="max-h-40 overflow-y-auto space-y-1 pr-1">
                      {recentHistoryEntries.length > 0 ? (
                        recentHistoryEntries.map((command, index) => (
                          <button
                            type="button"
                            key={`${command}-${index}`}
                            onClick={() => handleHistoryEntrySelect(command)}
                            className="w-full text-left px-2 py-1 rounded hover:bg-dark-700 text-dark-200 transition-colors truncate"
                          >
                            {command}
                          </button>
                        ))
                      ) : (
                        <div className="text-dark-500">No history yet</div>
                      )}
                    </div>
                  </div>
                )}
                <div ref={terminalOutputRef} className="terminal-output-container space-y-1">
                  {terminalOutput.map((line) => (
                    <div
                      key={line.id}
                      className={`whitespace-pre-wrap ${
                        line.type === 'stderr'
                          ? 'text-red-400'
                          : line.type === 'command'
                            ? 'text-primary-400'
                            : line.type === 'error'
                              ? 'text-red-500'
                              : line.type === 'info'
                                ? 'text-dark-100'
                                : 'text-dark-300'
                      }`}
                    >
                      {line.text}
                    </div>
                  ))}
                  {isTerminalBusy && (
                    <div className="flex items-center text-dark-500 space-x-3">
                      <div className="flex items-center">
                        <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                        <span>{isStoppingTerminal ? 'Stopping...' : 'Running...'}</span>
                      </div>
                      <button
                        type="button"
                        onClick={handleStopTerminalCommand}
                        disabled={isStoppingTerminal}
                        className={`text-xs px-2 py-1 rounded border border-dark-600 transition-colors ${
                          isStoppingTerminal
                            ? 'text-dark-600 cursor-not-allowed'
                            : 'text-red-400 hover:text-red-300 border-red-500/50'
                        }`}
                      >
                        Stop
                      </button>
                    </div>
                  )}
                </div>
                <div className="flex items-center space-x-2 mt-4">
                  <span className="text-dark-400">$</span>
                  <input
                    ref={terminalInputRef}
                    type="text"
                    value={terminalInput}
                    onChange={handleTerminalInputChange}
                    onKeyDown={handleTerminalInputKeyDown}
                    className="flex-1 bg-transparent border-none outline-none text-dark-200 disabled:opacity-50"
                    placeholder="Type command..."
                    disabled={isTerminalBusy}
                  />
                </div>
                {!isTerminalBusy && isCompletingTerminal && (
                  <div className="flex items-center text-dark-500 text-xs mt-2">
                    <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                    <span>Auto-completing...</span>
                  </div>
                )}
              </div>
            )}
            {bottomPanelTab === 'problems' && (
              <div className="flex items-center justify-center h-full text-dark-400">
                <div className="text-center">
                  <CheckCircle className="w-8 h-8 mx-auto mb-2 text-green-500" />
                  <div>No problems detected</div>
                </div>
              </div>
            )}
            {bottomPanelTab === 'output' && (
              <div className="text-dark-400">
                <div className="text-xs text-dark-500 mb-2">Output will appear here...</div>
              </div>
            )}
            {bottomPanelTab === 'debug console' && (
              <div className="text-dark-400">
                <div className="text-xs text-dark-500 mb-2">Debug console - Ready</div>
              </div>
            )}
            {bottomPanelTab === 'ports' && (
              <div className="text-dark-400">
                <div className="text-xs text-dark-500 mb-2">No active ports</div>
              </div>
            )}
          </div>
          </div>
          {/* Bottom Resize Handle */}
          <div
            onMouseDown={() => setIsResizingBottom(true)}
            className="h-1 bg-dark-700 hover:bg-primary-500 cursor-row-resize transition-colors w-full"
            style={{ minHeight: '4px' }}
            title="Drag to resize"
          />
        </>
      )}

      {/* Panel Toggle Buttons */}
      {!leftSidebarVisible && (
        <button
          onClick={() => setLeftSidebarVisible(true)}
          className="absolute left-0 top-1/2 bg-dark-800 border-r border-y border-dark-700 p-1 rounded-r"
        >
          <ChevronRight className="w-4 h-4 text-dark-400" />
        </button>
      )}
      {!rightSidebarVisible && (
        <button
          onClick={() => setRightSidebarVisible(true)}
          className="absolute right-0 top-1/2 bg-dark-800 border-l border-y border-dark-700 p-1 rounded-l"
        >
          <ChevronLeft className="w-4 h-4 text-dark-400" />
        </button>
      )}
      {!bottomPanelVisible && (
        <button
          onClick={() => setBottomPanelVisible(true)}
          className="absolute bottom-0 left-1/2 transform -translate-x-1/2 bg-dark-800 border-t border-x border-dark-700 p-1 rounded-t"
        >
          <Maximize2 className="w-4 h-4 text-dark-400" />
        </button>
      )}
      {showConnectivityPanel && (
        <div className="fixed inset-0 z-[999] bg-black/60 flex items-center justify-center px-4">
          <div className="bg-dark-900 border border-dark-700 rounded-2xl w-full max-w-2xl shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b border-dark-700">
              <div>
                <h3 className="text-lg font-semibold text-white">Connectivity Settings</h3>
                <p className="text-xs text-dark-400">Configure Ollama endpoints and proxy preferences</p>
              </div>
              <button
                onClick={() => setShowConnectivityPanel(false)}
                className="p-2 rounded hover:bg-dark-800 transition-colors"
              >
                <X className="w-4 h-4 text-dark-300" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              {isConnectivityLoading || !connectivitySettings ? (
                <div className="flex items-center justify-center py-10 text-dark-400">
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Loading connectivity settings...
                </div>
              ) : (
                <>
                  <div>
                    <label className="text-xs uppercase tracking-wide text-dark-400">Ollama Proxy URL</label>
                    <input
                      type="text"
                      value={connectivitySettings.ollamaUrl}
                      onChange={(e) => handleConnectivityChange('ollamaUrl', e.target.value)}
                      className="mt-1 w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded text-sm text-dark-100 focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-wide text-dark-400">Ollama Direct URL</label>
                    <input
                      type="text"
                      value={connectivitySettings.ollamaDirectUrl}
                      onChange={(e) => handleConnectivityChange('ollamaDirectUrl', e.target.value)}
                      className="mt-1 w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded text-sm text-dark-100 focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-sm text-dark-200">
                    <input
                      type="checkbox"
                      checked={!!connectivitySettings.useProxy}
                      onChange={(e) => handleConnectivityChange('useProxy', e.target.checked)}
                      className="form-checkbox text-primary-500 rounded"
                    />
                    Use proxy before direct connection
                  </label>
                  <div>
                    <label className="text-xs uppercase tracking-wide text-dark-400">AI Model</label>
                    <div className="mt-1 relative">
                      {isLoadingModels ? (
                        <div className="flex items-center gap-2 px-3 py-2 bg-dark-800 border border-dark-600 rounded text-sm text-dark-400">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Loading models...
                        </div>
                      ) : (
                        <select
                          value={connectivitySettings.currentModel || ''}
                          onChange={(e) => handleConnectivityChange('currentModel', e.target.value)}
                          className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded text-sm text-dark-100 focus:outline-none focus:ring-1 focus:ring-primary-500 appearance-none cursor-pointer"
                        >
                          {ollamaModels.length === 0 ? (
                            <option value="">No models available</option>
                          ) : (
                            ollamaModels.map((model) => (
                              <option key={model} value={model} className="bg-dark-800">
                                {model}
                              </option>
                            ))
                          )}
                        </select>
                      )}
                      {!isLoadingModels && ollamaModels.length > 0 && (
                        <div className="absolute right-2 top-1/2 transform -translate-y-1/2 pointer-events-none">
                          <ChevronDown className="w-4 h-4 text-dark-400" />
                        </div>
                      )}
                    </div>
                    {ollamaModels.length > 0 && (
                      <p className="text-xs text-dark-500 mt-1">
                        {ollamaModels.length} model{ollamaModels.length !== 1 ? 's' : ''} available from Ollama
                      </p>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="bg-dark-800 border border-dark-700 rounded-xl p-3">
                      <div className="text-dark-400 text-xs uppercase">Backend</div>
                      <div className="flex items-center gap-2 mt-2">
                        {isConnected ? (
                          <CheckCircle className="w-4 h-4 text-green-500" />
                        ) : (
                          <AlertCircle className="w-4 h-4 text-red-500" />
                        )}
                        <span className="text-dark-100">
                          {isConnected ? 'Online' : 'Offline'}
                        </span>
                      </div>
                    </div>
                    <div className="bg-dark-800 border border-dark-700 rounded-xl p-3">
                      <div className="text-dark-400 text-xs uppercase">Ollama</div>
                      <div className="flex items-center gap-2 mt-2">
                        {chatStatus?.ollama_connected ? (
                          <CheckCircle className="w-4 h-4 text-green-500" />
                        ) : (
                          <AlertCircle className="w-4 h-4 text-red-500" />
                        )}
                        <span className="text-dark-100">
                          {chatStatus?.ollama_connected ? 'Connected' : 'Disconnected'}
                        </span>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
            <div className="px-6 py-4 border-t border-dark-700 flex items-center justify-between">
              <div className="text-xs text-dark-500">
                Changes apply immediately after saving. Use test to verify Ollama reachability.
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleTestConnectivity}
                  disabled={isTestingConnectivity || isConnectivityLoading}
                  className="px-3 py-2 rounded-lg border border-dark-600 text-dark-100 text-sm hover:bg-dark-800 disabled:opacity-50"
                >
                  {isTestingConnectivity ? 'Testing…' : 'Test Connection'}
                </button>
                <button
                  type="button"
                  onClick={handleSaveConnectivity}
                  disabled={isConnectivitySaving || isConnectivityLoading}
                  className="px-4 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-sm disabled:opacity-50"
                >
                  {isConnectivitySaving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* File/Folder Picker Modal */}
      {(showFolderPicker || showFilePicker) && (
        <div className="fixed inset-0 z-[999] bg-black/60 flex items-center justify-center px-4">
          <div className="bg-dark-900 border border-dark-700 rounded-lg w-full max-w-4xl shadow-2xl flex flex-col" style={{ maxHeight: '80vh' }}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-dark-700">
              <h3 className="text-lg font-semibold text-white">
                {pickerMode === 'folder' ? (showFolderPicker ? 'Open Folder' : 'Select Folder') : 'Select File Path'}
              </h3>
              <button
                onClick={() => {
                  setShowFolderPicker(false);
                  setShowFilePicker(false);
                }}
                className="p-2 rounded hover:bg-dark-800 transition-colors"
              >
                <X className="w-4 h-4 text-dark-300" />
              </button>
            </div>

            {/* Navigation Bar */}
            <div className="px-4 py-2 border-b border-dark-700 bg-dark-800 flex items-center gap-2">
              <div className="flex items-center gap-1">
                <button
                  onClick={async () => {
                    const parentPath = pickerPath.split('/').slice(0, -1).join('/') || '.';
                    await loadPickerTree(parentPath);
                  }}
                  className="p-1 hover:bg-dark-700 rounded"
                  title="Up"
                >
                  <ChevronLeft className="w-4 h-4 text-dark-400" />
                </button>
              </div>
              <div className="flex-1 flex items-center gap-2 px-2 py-1 bg-dark-700 rounded text-sm text-dark-300">
                <span className="truncate">{pickerPath || '.'}</span>
              </div>
              <button
                onClick={() => loadPickerTree(pickerPath)}
                className="p-1 hover:bg-dark-700 rounded"
                title="Refresh"
              >
                <Loader2 className={`w-4 h-4 text-dark-400 ${pickerLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden flex">
              {/* Left Pane - File Tree */}
              <div className="w-64 border-r border-dark-700 overflow-y-auto bg-dark-800">
                <div className="p-2">
                  {pickerLoading ? (
                    <div className="flex items-center justify-center py-8 text-dark-400">
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                      Loading...
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {pickerTree.map((item) => (
                        <div
                          key={item.path}
                          onClick={async () => {
                            if (item.is_directory) {
                              await loadPickerTree(item.path);
                            }
                            setPickerSelectedPath(item.path);
                          }}
                          className={`flex items-center px-2 py-1.5 rounded cursor-pointer text-sm ${
                            pickerSelectedPath === item.path
                              ? 'bg-primary-600 text-white'
                              : 'text-dark-300 hover:bg-dark-700'
                          }`}
                        >
                          {item.is_directory ? (
                            <Folder className="w-4 h-4 mr-2 flex-shrink-0" />
                          ) : (
                            <File className="w-4 h-4 mr-2 flex-shrink-0" />
                          )}
                          <span className="truncate">{item.name}</span>
                        </div>
                      ))}
                      {pickerTree.length === 0 && (
                        <div className="text-xs text-dark-400 py-4 text-center">No items</div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Right Pane - Details (optional, can be simplified) */}
              <div className="flex-1 p-4">
                {pickerSelectedPath && (
                  <div className="mb-4">
                    <label className="block text-sm text-dark-400 mb-2">
                      Selected {pickerMode === 'folder' ? 'Folder' : 'Path'}:
                    </label>
                    <input
                      type="text"
                      value={pickerSelectedPath}
                      onChange={(e) => setPickerSelectedPath(e.target.value)}
                      className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded text-sm text-dark-100 focus:outline-none focus:ring-1 focus:ring-primary-500"
                      placeholder={pickerMode === 'folder' ? 'Enter folder path...' : 'Enter file path...'}
                    />
                  </div>
                )}
                {!pickerSelectedPath && (
                  <div className="flex items-center justify-center h-full text-dark-400">
                    Select a {pickerMode === 'folder' ? 'folder' : 'file'} from the list
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="px-4 py-3 border-t border-dark-700 flex items-center justify-end gap-2">
              <button
                onClick={() => {
                  setShowFolderPicker(false);
                  setShowFilePicker(false);
                }}
                className="px-4 py-2 rounded-lg border border-dark-600 text-dark-200 text-sm hover:bg-dark-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (showFolderPicker) {
                    handleFolderPickerSelect();
                  } else if (pickerMode === 'folder') {
                    handleFolderPickerConfirm();
                  } else if (pickerMode === 'file') {
                    // Check if it's save as or create file
                    if (activeTab) {
                      handleSaveAsConfirm();
                    } else {
                      handleFilePickerConfirm();
                    }
                  }
                }}
                className="px-4 py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-sm transition-colors"
              >
                {showFolderPicker ? 'Select Folder' : pickerMode === 'folder' ? 'Create' : activeTab ? 'Save' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {fileContextMenu.visible && contextMenuItems.length > 0 && (
        <div className="fixed inset-0 z-50" onClick={closeFileContextMenu}>
          <div
            className="file-context-menu absolute bg-dark-800 border border-dark-600 rounded-lg shadow-2xl min-w-[260px] py-2 text-sm text-dark-50"
            style={{ top: fileContextMenu.y, left: fileContextMenu.x }}
            onClick={(e) => e.stopPropagation()}
          >
            {contextMenuItems.map((item, index) => {
              if (item.type === 'separator') {
                return <div key={`sep-${index}`} className="my-1 border-t border-dark-700" />;
              }
              if (item.children) {
                return (
                  <div key={item.label} className="relative group">
                    <button
                      type="button"
                      className="w-full flex items-center justify-between px-3 py-2 hover:bg-dark-700 text-left"
                    >
                      <span className="flex items-center gap-2">
                        {item.icon && <item.icon className="w-4 h-4 text-dark-400" />}
                        {item.label}
                      </span>
                      <ChevronRightIcon className="w-3 h-3 text-dark-500" />
                    </button>
                    <div className="absolute top-0 left-full ml-1 hidden group-hover:block bg-dark-800 border border-dark-600 rounded-lg min-w-[220px] shadow-2xl py-2">
                      {item.children.map((child, childIndex) => (
                        <button
                          type="button"
                          key={`${child.label}-${childIndex}`}
                          onClick={() => child.action?.()}
                          className="w-full flex items-center justify-between px-3 py-2 text-sm text-dark-100 hover:bg-dark-700"
                        >
                          <span>{child.label}</span>
                          {child.shortcut && (
                            <span className="text-[11px] text-dark-500">{child.shortcut}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              }
              return (
                <button
                  type="button"
                  key={`${item.label}-${index}`}
                  disabled={item.disabled}
                  onClick={() => {
                    if (!item.disabled) {
                      item.action?.();
                    }
                  }}
                  className={`w-full flex items-center px-3 py-2 text-left gap-2 ${
                    item.disabled
                      ? 'text-dark-500 cursor-not-allowed'
                      : 'text-dark-100 hover:bg-dark-700'
                  }`}
                >
                  <span className="flex-1">{item.label}</span>
                  {item.shortcut && (
                    <span className="text-[11px] text-dark-500">{item.shortcut}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {comparisonState?.diff && (
        <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center px-4">
          <div className="bg-dark-900 border border-dark-600 rounded-xl shadow-2xl max-w-5xl w-full max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-dark-700">
              <div>
                <div className="text-dark-100 font-semibold text-sm">
                  Comparing {comparisonState.leftLabel} ↔ {comparisonState.rightLabel}
                </div>
                <div className="text-[11px] text-dark-500">{comparisonState.rightPath}</div>
              </div>
              <button
                type="button"
                className="p-1 rounded hover:bg-dark-700"
                onClick={() => setComparisonState(null)}
              >
                <X className="w-4 h-4 text-dark-400" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto text-xs font-mono bg-dark-950 px-4 py-3 space-y-1">
              {comparisonState.diff.map((line, idx) => {
                const baseClasses = 'px-2 py-0.5 rounded';
                if (line.type === 'added') {
                  return (
                    <div key={idx} className={`${baseClasses} bg-green-900/40 text-green-200`}>
                      + {line.text}
                    </div>
                  );
                }
                if (line.type === 'removed') {
                  return (
                    <div key={idx} className={`${baseClasses} bg-red-900/40 text-red-200`}>
                      - {line.text}
                    </div>
                  );
                }
                if (line.type === 'skip') {
                  return (
                    <div key={idx} className="text-dark-500 italic">
                      {line.text}
                    </div>
                  );
                }
                return (
                  <div key={idx} className={`${baseClasses} text-dark-200`}>
                    {line.text}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IDELayout;

