import { marked } from 'marked';

/**
 * Comprehensive message formatting utility
 * Based on the reference Ollama chat implementation
 */

const CALLOUT_ICONS = '💡🔍⚠️✅❌📝🎯';
let rendererInstance = null;

const safeStringifyValue = (value, spacing = 2) => {
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

const ensureRenderer = () => {
  if (rendererInstance) {
    return rendererInstance;
  }

  const renderer = new marked.Renderer();

  renderer.code = (code, infoString = '') => {
    const language = (infoString || '').split(/\s+/)[0];
    const lang = normalizeLanguage(language || 'text');
    const escapedCode = escapeHtml((code || '').trimEnd());

    return `<div class="code-block language-${lang}" data-language="${lang}">
      <div class="code-header">
        <span class="code-language">${lang}</span>
        <button class="copy-code-btn" type="button" title="Copy code" aria-label="Copy code">
          <span class="copy-icon" aria-hidden="true">📋</span>
          <span class="copy-text">Copy</span>
        </button>
      </div>
      <pre><code class="language-${lang}">${escapedCode}</code></pre>
    </div>`;
  };

  renderer.list = (body, ordered, start) => {
    const tag = ordered ? 'ol' : 'ul';
    const startAttr = ordered && typeof start === 'number' && start !== 1 ? ` start="${start}"` : '';
    return `<${tag}${startAttr}>${body}</${tag}>`;
  };

  renderer.listitem = (text, task, checked) => {
    if (task) {
      return `<li class="task-item" data-checked="${checked ? 'x' : ' '}">${text}</li>`;
    }
    return `<li>${text}</li>`;
  };

  renderer.link = (href, title, text) => {
    const safeHref = href || '#';
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
    return `<a href="${safeHref}"${titleAttr} target="_blank" rel="noopener noreferrer" class="markdown-link">${text}</a>`;
  };

  renderer.image = (href, title, text) => {
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
    return `<img src="${href}" alt="${escapeHtml(text || '')}"${titleAttr} class="markdown-image" loading="lazy">`;
  };

  renderer.table = (header, body) => {
    const tableHeader = header ? `<thead>${header}</thead>` : '';
    const tableBody = body ? `<tbody>${body}</tbody>` : '<tbody></tbody>';
    return `<table class="markdown-table">${tableHeader}${tableBody}</table>`;
  };

  renderer.text = (text) => formatInlineMarkdown(escapeHtml(text || ''));

  marked.setOptions({
    renderer,
    gfm: true,
    breaks: true,
    smartLists: true,
    mangle: false,
    headerIds: false
  });

  rendererInstance = renderer;
  return rendererInstance;
};

const normalizeInputContent = (content) => {
  if (content == null) {
    return '';
  }
  if (typeof content === 'string' || typeof content === 'number' || typeof content === 'boolean') {
    return String(content);
  }
  if (Array.isArray(content)) {
    return content
      .map((item) => normalizeInputContent(item))
      .filter((segment) => segment !== '')
      .join('\n\n');
  }
  if (typeof content === 'object') {
    try {
      return safeStringifyValue(content, 2);
    } catch (error) {
      // Debug fallback to help track down [object Object] issues
      // eslint-disable-next-line no-console
      console.log(
        'normalizeInputContent: failed to stringify object content, using Object.toString fallback',
        {
          contentType: Object.prototype.toString.call(content),
          content,
          error,
        }
      );
      return Object.prototype.toString.call(content);
    }
  }
  return String(content);
};

const applyCalloutEnhancements = (html) => {
  if (!html) return html;

  const calloutRegex = new RegExp(
    `<blockquote>\\s*<p>([${CALLOUT_ICONS}])\\s*<strong>([^<]+)</strong>:\\s*([\\s\\S]*?)</p>([\\s\\S]*?)</blockquote>`,
    'g'
  );

  return html.replace(calloutRegex, (match, icon, title, lead, rest) => {
    const leadContent = lead?.trim() ? `<p>${lead.trim()}</p>` : '';
    const trailingContent = rest?.trim() || '';
    const combinedContent = [leadContent, trailingContent].filter(Boolean).join('');

    return `<div class="callout callout-${icon}">
      <div class="callout-header">
        <span class="callout-icon">${icon}</span>
        <strong>${title.trim()}</strong>
      </div>
      <div class="callout-content">
        ${combinedContent}
      </div>
    </div>`;
  });
};

export const formatMessageContent = (content) => {
  const renderer = ensureRenderer();
  const normalized = normalizeInputContent(content).replace(/\r\n/g, '\n');
  let formattedContent = '';

  try {
    formattedContent = marked.parse(normalized, { renderer });
  } catch (error) {
    // eslint-disable-next-line no-console
    console.log('formatMessageContent: marked.parse threw, falling back to plain text HTML', {
      error,
      normalized,
    });
    formattedContent = '';
  }

  formattedContent = applyCalloutEnhancements(formattedContent);

  // If something in the markdown pipeline produced [object Object],
  // fall back to a very simple escaped HTML representation so the
  // user at least sees the actual text instead of the JS object tag.
  const trimmed = (formattedContent || '').trim();
  if (
    !trimmed ||
    trimmed === '[object Object]' ||
    trimmed === '<p>[object Object]</p>' ||
    trimmed === '<p>[object Object]</p>\n' ||
    /\[object Object\]/.test(trimmed)
  ) {
    const safe = escapeHtml(normalized);
    return `<p>${safe.replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br />')}</p>`;
  }

  return formattedContent;
};

export const formatInlineMarkdown = (text) => {
  let formatted = text;
  
  // Handle mathematical formulas and scientific notation first
  // Process LaTeX delimiters - handle various escaping scenarios
  // First, handle display math (double dollar signs)
  formatted = formatted.replace(/\$\$([^$]+)\$\$/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  // Handle inline math (single dollar signs) - but be careful not to match currency
  formatted = formatted.replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, (match, content) => {
    // Skip if it looks like currency (contains only numbers, commas, dots)
    if (/^[\d,.\s]+$/.test(content.trim())) {
      return match;
    }
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  // Handle LaTeX delimiters with backslashes
  // Inline math: \( ... \)
  formatted = formatted.replace(/\\\(([^)]+)\\\)/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  // Display math: \[ ... \]
  formatted = formatted.replace(/\\\[([^\]]+)\\\]/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  // Handle HTML-escaped backslashes
  formatted = formatted.replace(/&#92;\(([^)]+)\&#92;\)/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  formatted = formatted.replace(/&#92;\[([^\]]+)\&#92;\]/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  // Since LaTeX delimiters aren't being caught, let's process mathematical content directly
  // This will handle the content even if the delimiters aren't being processed
  
  // Handle common mathematical symbols first
  formatted = formatted.replace(/\\alpha/g, 'α');
  formatted = formatted.replace(/\\beta/g, 'β');
  formatted = formatted.replace(/\\gamma/g, 'γ');
  formatted = formatted.replace(/\\delta/g, 'δ');
  formatted = formatted.replace(/\\epsilon/g, 'ε');
  formatted = formatted.replace(/\\theta/g, 'θ');
  formatted = formatted.replace(/\\lambda/g, 'λ');
  formatted = formatted.replace(/\\mu/g, 'μ');
  formatted = formatted.replace(/\\pi/g, 'π');
  formatted = formatted.replace(/\\sigma/g, 'σ');
  formatted = formatted.replace(/\\tau/g, 'τ');
  formatted = formatted.replace(/\\phi/g, 'φ');
  formatted = formatted.replace(/\\omega/g, 'ω');
  formatted = formatted.replace(/\\infty/g, '∞');
  formatted = formatted.replace(/\\sum/g, '∑');
  formatted = formatted.replace(/\\int/g, '∫');
  formatted = formatted.replace(/\\partial/g, '∂');
  formatted = formatted.replace(/\\nabla/g, '∇');
  formatted = formatted.replace(/\\times/g, '×');
  formatted = formatted.replace(/\\div/g, '÷');
  formatted = formatted.replace(/\\pm/g, '±');
  formatted = formatted.replace(/\\leq/g, '≤');
  formatted = formatted.replace(/\\geq/g, '≥');
  formatted = formatted.replace(/\\neq/g, '≠');
  formatted = formatted.replace(/\\approx/g, '≈');
  formatted = formatted.replace(/\\propto/g, '∝');
  formatted = formatted.replace(/\\in/g, '∈');
  formatted = formatted.replace(/\\subset/g, '⊂');
  formatted = formatted.replace(/\\supset/g, '⊃');
  formatted = formatted.replace(/\\cup/g, '∪');
  formatted = formatted.replace(/\\cap/g, '∩');
  formatted = formatted.replace(/\\emptyset/g, '∅');
  
  // Handle square root patterns
  formatted = formatted.replace(/\\sqrt\{([^}]+)\}/g, '<span class="math-function">√($1)</span>');
  
  // Handle summation patterns
  formatted = formatted.replace(/\\sum_\{([^}]+)\}\^\{([^}]+)\}/g, '<span class="math-function">∑<sub>$1</sub><sup>$2</sup></span>');
  
  // Handle integral patterns
  formatted = formatted.replace(/\\int_\{([^}]+)\}\^\{([^}]+)\}/g, '<span class="math-function">∫<sub>$1</sub><sup>$2</sup></span>');
  
  // Handle fractions
  formatted = formatted.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '<span class="math-fraction">$1/$2</span>');
  
  // Handle superscripts and subscripts in LaTeX format
  formatted = formatted.replace(/\^\{([^}]+)\}/g, '<sup>$1</sup>');
  formatted = formatted.replace(/_\{([^}]+)\}/g, '<sub>$1</sub>');
  formatted = formatted.replace(/\^([a-zA-Z0-9])/g, '<sup>$1</sup>');
  formatted = formatted.replace(/_([a-zA-Z0-9])/g, '<sub>$1</sub>');
  
  // Handle common mathematical patterns
  formatted = formatted.replace(/\b(\w+)_(\d+)\b/g, '<span class="math-subscript">$1<sub>$2</sub></span>');
  formatted = formatted.replace(/\b(\w+)_(\w+)\b/g, '<span class="math-subscript">$1<sub>$2</sub></span>');
  formatted = formatted.replace(/\b(\d+)\^(\d+)\b/g, '<span class="math-superscript">$1<sup>$2</sup></span>');
  
  // Handle fractions: a/b
  formatted = formatted.replace(/\b(\d+)\/(\d+)\b/g, '<span class="math-fraction">$1⁄$2</span>');
  
  // Handle Greek letters and common symbols in regular text (not in LaTeX delimiters)
  const mathSymbols = {
    'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε',
    'theta': 'θ', 'lambda': 'λ', 'mu': 'μ', 'pi': 'π', 'sigma': 'σ',
    'tau': 'τ', 'phi': 'φ', 'omega': 'ω', 'infinity': '∞', 'sum': '∑',
    'integral': '∫', 'partial': '∂', 'nabla': '∇', 'times': '×', 'divide': '÷',
    'plusminus': '±', 'lessequal': '≤', 'greaterequal': '≥', 'notequal': '≠',
    'approx': '≈', 'proportional': '∝', 'element': '∈', 'subset': '⊂',
    'superset': '⊃', 'union': '∪', 'intersection': '∩', 'empty': '∅'
  };
  
  Object.entries(mathSymbols).forEach(([word, symbol]) => {
    const regex = new RegExp(`\\b${word}\\b`, 'gi');
    formatted = formatted.replace(regex, `<span class="math-symbol">${symbol}</span>`);
  });
  
  // Handle chemical formulas (H2O, CO2, etc.)
  formatted = formatted.replace(/\b([A-Z][a-z]?)(\d+)\b/g, '<span class="chemical-formula">$1<sub>$2</sub></span>');
  
  // Handle units and measurements
  formatted = formatted.replace(/\b(\d+(?:\.\d+)?)\s*(m|kg|s|A|K|mol|cd|Hz|N|J|W|V|F|H|T|Pa|C|Wb|lm|lx|Bq|Gy|Sv|kat|m2|m3|kg\/m3|m\/s|m\/s2|N\/m2|J\/kg|W\/m2|V\/m|A\/m|T\/m|H\/m|F\/m|S\/m|Wb\/m|J\/K|Pa\*s|N\*s|kg\*m\/s|J\*s|W\*s|V\*A|A\*s|C\*V|F\*V2|H\*A2|T\*A\*m|Wb\*A|N\*m|Pa\*m3|J\/mol|V\*s|C\*s|F\*V|H\*A|T\*m|Wb\*s|kg\*m2\/s|N\*s\*m|Pa\*s\*m3|J\/(mol\*K)|W\/(m2\*K)|V\*s\/m|A\*s\/m|C\*s\/m|F\*V\/m|H\*A\/m|T\*m\/m|Wb\*s\/m|J\*s\/m|kg\*m2\/(s\*m)|N\*s\*m\/m|Pa\*s\*m3\/m|J\/(mol\*K\*m)|W\/(m2\*K\*m))\b/g, 
    '<span class="measurement">$1 <span class="unit">$2</span></span>');
  
  // Bold and italic
  formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  
  // Inline code
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  
  return formatted;
};

export const processMathContent = (content) => {
  let processed = content;
  
  // Handle Greek letters and common symbols first
  const mathSymbols = {
    '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ', '\\epsilon': 'ε',
    '\\theta': 'θ', '\\lambda': 'λ', '\\mu': 'μ', '\\pi': 'π', '\\sigma': 'σ',
    '\\tau': 'τ', '\\phi': 'φ', '\\omega': 'ω', '\\infty': '∞', '\\sum': '∑',
    '\\int': '∫', '\\partial': '∂', '\\nabla': '∇', '\\times': '×', '\\div': '÷',
    '\\pm': '±', '\\leq': '≤', '\\geq': '≥', '\\neq': '≠', '\\approx': '≈',
    '\\propto': '∝', '\\in': '∈', '\\subset': '⊂', '\\supset': '⊃',
    '\\cup': '∪', '\\cap': '∩', '\\emptyset': '∅', '\\sqrt': '√',
    '\\rightarrow': '→', '\\leftarrow': '←', '\\leftrightarrow': '↔',
    '\\Rightarrow': '⇒', '\\Leftarrow': '⇐', '\\Leftrightarrow': '⇔',
    '\\forall': '∀', '\\exists': '∃', '\\neg': '¬', '\\land': '∧', '\\lor': '∨',
    '\\rightarrow': '→', '\\leftarrow': '←', '\\leftrightarrow': '↔',
    '\\Rightarrow': '⇒', '\\Leftarrow': '⇐', '\\Leftrightarrow': '⇔',
    '\\cdot': '·', '\\bullet': '•', '\\circ': '∘', '\\star': '⋆',
    '\\oplus': '⊕', '\\ominus': '⊖', '\\otimes': '⊗', '\\odot': '⊙'
  };
  
  Object.entries(mathSymbols).forEach(([word, symbol]) => {
    const regex = new RegExp(word.replace(/\\/g, '\\\\'), 'g');
    processed = processed.replace(regex, symbol);
  });
  
  // Handle mathematical functions with proper nesting
  // Square root
  processed = processed.replace(/\\sqrt\{([^}]+)\}/g, '√($1)');
  
  // Fractions - handle nested braces
  processed = processed.replace(/\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g, 
    '<span class="math-fraction"><span class="numerator">$1</span><span class="denominator">$2</span></span>');
  
  // Summation and integration with limits
  processed = processed.replace(/\\sum_\{([^}]+)\}\^\{([^}]+)\}/g, '∑<sub>$1</sub><sup>$2</sup>');
  processed = processed.replace(/\\int_\{([^}]+)\}\^\{([^}]+)\}/g, '∫<sub>$1</sub><sup>$2</sup>');
  
  // Handle superscripts and subscripts in LaTeX with proper nesting
  processed = processed.replace(/\^\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g, '<sup>$1</sup>');
  processed = processed.replace(/_\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g, '<sub>$1</sub>');
  processed = processed.replace(/\^([a-zA-Z0-9])/g, '<sup>$1</sup>');
  processed = processed.replace(/_([a-zA-Z0-9])/g, '<sub>$1</sub>');
  
  // Handle common mathematical patterns
  processed = processed.replace(/\b(\w+)_(\d+)\b/g, '$1<sub>$2</sub>');
  processed = processed.replace(/\b(\w+)_(\w+)\b/g, '$1<sub>$2</sub>');
  processed = processed.replace(/\b(\d+)\^(\d+)\b/g, '$1<sup>$2</sup>');
  
  // Handle fractions in simple form
  processed = processed.replace(/\b(\d+)\/(\d+)\b/g, '<span class="math-fraction">$1⁄$2</span>');
  
  // Handle bold vectors and text formatting
  processed = processed.replace(/\\mathbf\{([^}]+)\}/g, '<strong>$1</strong>');
  processed = processed.replace(/\\text\{([^}]+)\}/g, '$1');
  processed = processed.replace(/\\textbf\{([^}]+)\}/g, '<strong>$1</strong>');
  processed = processed.replace(/\\textit\{([^}]+)\}/g, '<em>$1</em>');
  
  // Handle parentheses and brackets
  processed = processed.replace(/\\left\(/g, '(');
  processed = processed.replace(/\\right\)/g, ')');
  processed = processed.replace(/\\left\[/g, '[');
  processed = processed.replace(/\\right\]/g, ']');
  processed = processed.replace(/\\left\{/g, '{');
  processed = processed.replace(/\\right\}/g, '}');
  
  // Handle spaces and alignment
  processed = processed.replace(/\\,|\\:|\\;|\\quad|\\qquad/g, ' ');
  processed = processed.replace(/\\hspace\{[^}]+\}/g, ' ');
  
  return processed;
};

export const normalizeLanguage = (lang) => {
  if (!lang) return 'text';
  
  const languageMap = {
    // Common variations
    'js': 'javascript',
    'ts': 'typescript',
    'py': 'python',
    'rb': 'ruby',
    'sh': 'bash',
    'yml': 'yaml',
    'docker': 'dockerfile',
    'dockerfile': 'dockerfile',
    'c++': 'cpp',
    'c#': 'csharp',
    'cs': 'csharp',
    'go': 'go',
    'golang': 'go',
    'rs': 'rust',
    'kt': 'kotlin',
    'swift': 'swift',
    'php': 'php',
    'java': 'java',
    'sql': 'sql',
    'html': 'html',
    'htm': 'html',
    'xml': 'xml',
    'css': 'css',
    'scss': 'scss',
    'sass': 'sass',
    'less': 'less',
    'json': 'json',
    'yaml': 'yaml',
    'markdown': 'markdown',
    'md': 'markdown',
    'txt': 'text',
    'text': 'text',
    'plain': 'text',
    'plaintext': 'text',
    'bash': 'bash',
    'shell': 'bash',
    'zsh': 'bash',
    'fish': 'bash',
    'powershell': 'powershell',
    'ps1': 'powershell',
    'cmd': 'batch',
    'bat': 'batch',
    'batch': 'batch',
    'vim': 'vim',
    'viml': 'vim',
    'lua': 'lua',
    'perl': 'perl',
    'pl': 'perl',
    'r': 'r',
    'scala': 'scala',
    'clojure': 'clojure',
    'clj': 'clojure',
    'haskell': 'haskell',
    'hs': 'haskell',
    'elm': 'elm',
    'dart': 'dart',
    'flutter': 'dart',
    'vue': 'vue',
    'svelte': 'svelte',
    'angular': 'typescript',
    'react': 'javascript',
    'node': 'javascript',
    'nodejs': 'javascript',
    'npm': 'json',
    'package': 'json',
    'config': 'json',
    'ini': 'ini',
    'toml': 'toml',
    'env': 'bash',
    'gitignore': 'gitignore',
    'gitattributes': 'gitattributes',
    'dockerignore': 'dockerignore',
    'makefile': 'makefile',
    'cmake': 'cmake',
    'gradle': 'gradle',
    'maven': 'xml',
    'pom': 'xml',
    'ant': 'xml',
    'log': 'text',
    'diff': 'diff',
    'patch': 'diff'
  };
  
  const normalized = languageMap[lang.toLowerCase()] || lang.toLowerCase();
  return normalized;
};

export const escapeHtml = (text) => {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
};

// Copy to clipboard functionality
export const copyToClipboard = async (text, button) => {
  try {
    const cleanText = typeof text === 'string' ? text : (text ?? '').toString();
    
    if (!cleanText.length) {
      return false;
    }
    
    const canUseModernClipboard = typeof navigator !== 'undefined' && navigator.clipboard && typeof window !== 'undefined' && window.isSecureContext;
    
    if (canUseModernClipboard) {
      await navigator.clipboard.writeText(cleanText);
    } else if (typeof document !== 'undefined') {
      const textArea = document.createElement('textarea');
      textArea.value = cleanText;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      textArea.style.top = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      const successful = document.execCommand('copy');
      document.body.removeChild(textArea);
      
      if (!successful) {
        throw new Error('execCommand failed');
      }
    } else {
      throw new Error('Clipboard API is not available');
    }
    
    if (button) {
      const originalIcon = button.innerHTML;
      button.classList.add('copied');
      button.innerHTML = '<span class="copy-icon" aria-hidden="true">✓</span><span class="copy-text">Copied</span>';
      button.title = 'Copied!';
      
      setTimeout(() => {
        button.classList.remove('copied');
        button.innerHTML = originalIcon;
        button.title = 'Copy code';
      }, 2000);
    }
    
    return true;
  } catch (error) {
    console.error('Failed to copy to clipboard:', error);
    
    if (button) {
      button.classList.remove('copied');
      button.innerHTML = '<span class="copy-icon" aria-hidden="true">📋</span><span class="copy-text">Copy</span>';
      button.title = 'Copy code';
    }
    
    return false;
  }
};

const getCodeTextFromButton = (button) => {
  if (!button) return '';
  const codeBlock = button.closest('.code-block');
  if (!codeBlock) return '';
  
  const hiddenTextarea = codeBlock.querySelector('textarea');
  if (hiddenTextarea && typeof hiddenTextarea.value === 'string' && hiddenTextarea.value.length) {
    return hiddenTextarea.value;
  }
  
  const codeElement = codeBlock.querySelector('code');
  return codeElement?.textContent ?? '';
};

const COPY_HANDLER_STORAGE_KEY = '__ai_agent_copy_code_handler__';

const handleCopyButtonClick = (event) => {
  const target = event.target instanceof Element ? event.target.closest('.copy-code-btn') : null;
  if (!target) return;
  
  event.preventDefault();
  event.stopPropagation();
  
  const codeText = getCodeTextFromButton(target);
  if (!codeText) return;
  
  copyToClipboard(codeText, target);
};

export const initializeCopyCodeListeners = () => {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return;
  }
  
  const existingHandler = window[COPY_HANDLER_STORAGE_KEY];
  if (existingHandler) {
    document.removeEventListener('click', existingHandler);
  }
  
  document.addEventListener('click', handleCopyButtonClick);
  window[COPY_HANDLER_STORAGE_KEY] = handleCopyButtonClick;
};
