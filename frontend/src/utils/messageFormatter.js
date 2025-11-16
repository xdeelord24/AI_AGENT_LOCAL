/**
 * Comprehensive message formatting utility
 * Based on the reference Ollama chat implementation
 */

export const formatMessageContent = (content) => {
  let formattedContent = content;
  
  // First, handle code blocks (before other processing)
  formattedContent = formattedContent.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, language, code) => {
    const lang = normalizeLanguage(language || 'text');
    const escapedCode = escapeHtml(code.trim());
    return `<div class="code-block language-${lang}" data-language="${lang}">
      <div class="code-header">
        <span class="code-language">${lang}</span>
        <button class="copy-code-btn" type="button" title="Copy code" aria-label="Copy code">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
          </svg>
        </button>
      </div>
      <pre><code class="language-${lang}">${escapedCode}</code></pre>
    </div>`;
  });
  
  // Handle tables
  formattedContent = formattedContent.replace(/\|(.+)\|\n\|([\s\-\|]+\|)\n((?:\|.+\|\n?)*)/g, (match, header, separator, rows) => {
    const headerCells = header.split('|').map(cell => cell.trim()).filter(cell => cell);
    const rowLines = rows.trim().split('\n').filter(line => line.trim());
    
    let tableHtml = '<table class="markdown-table">';
    
    // Header
    tableHtml += '<thead><tr>';
    headerCells.forEach(cell => {
      tableHtml += `<th>${escapeHtml(cell)}</th>`;
    });
    tableHtml += '</tr></thead>';
    
    // Body
    tableHtml += '<tbody>';
    rowLines.forEach(row => {
      const cells = row.split('|').map(cell => cell.trim()).filter(cell => cell);
      tableHtml += '<tr>';
      cells.forEach(cell => {
        tableHtml += `<td>${formatInlineMarkdown(cell)}</td>`;
      });
      tableHtml += '</tr>';
    });
    tableHtml += '</tbody></table>';
    
    return tableHtml;
  });
  
  // Handle headers
  formattedContent = formattedContent.replace(/^#{6}\s+(.+)$/gm, '<h6>$1</h6>');
  formattedContent = formattedContent.replace(/^#{5}\s+(.+)$/gm, '<h5>$1</h5>');
  formattedContent = formattedContent.replace(/^#{4}\s+(.+)$/gm, '<h4>$1</h4>');
  formattedContent = formattedContent.replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>');
  formattedContent = formattedContent.replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>');
  formattedContent = formattedContent.replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>');
  
  // Handle horizontal rules
  formattedContent = formattedContent.replace(/^---$/gm, '<hr>');
  
  // Handle blockquotes
  formattedContent = formattedContent.replace(/^>\s*(.+)$/gm, '<blockquote>$1</blockquote>');
  
  // Handle callouts (enhanced blockquotes with emojis)
  formattedContent = formattedContent.replace(/^>\s*([💡🔍⚠️✅❌📝🎯💡])\s*\*\*([^*]+)\*\*:\s*(.+)$/gm, '<div class="callout callout-$1"><div class="callout-header"><span class="callout-icon">$1</span><strong>$2</strong></div><div class="callout-content">$3</div></div>');
  
  // Handle bold, italic, and strikethrough text
  formattedContent = formattedContent.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  formattedContent = formattedContent.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  formattedContent = formattedContent.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  
  // Handle links and images
  formattedContent = formattedContent.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="markdown-link">$1</a>');
  formattedContent = formattedContent.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="markdown-image" loading="lazy">');
  
  // Handle inline code (after other processing to avoid conflicts)
  formattedContent = formattedContent.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  
  // Handle task lists (checkboxes) - must be before regular bullet lists
  formattedContent = formattedContent.replace(/^-\s+\[([ x])\]\s+(.+)$/gm, '<li class="task-item" data-checked="$1">$2</li>');
  
  // Handle bullet lists
  formattedContent = formattedContent.replace(/^\*\s+(.+)$/gm, '<li>$1</li>');
  formattedContent = formattedContent.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  
  // Handle numbered lists
  formattedContent = formattedContent.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
  
  // Handle line breaks and paragraphs
  const paragraphs = formattedContent.split('\n\n');
  formattedContent = paragraphs.map(para => {
    para = para.trim();
    if (para.startsWith('<') || para.includes('<table') || para.includes('<code-block')) {
      return para;
    }
    return `<p>${formatInlineMarkdown(para)}</p>`;
  }).join('\n');
  
  return formattedContent;
};

export const formatInlineMarkdown = (text) => {
  let formatted = text;
  
  // Handle mathematical formulas and scientific notation first
  console.log('Original text:', formatted);
  
  // Process LaTeX delimiters - handle various escaping scenarios
  // First, handle display math (double dollar signs)
  formatted = formatted.replace(/\$\$([^$]+)\$\$/g, (match, content) => {
    console.log('Found display math $$:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  // Handle inline math (single dollar signs) - but be careful not to match currency
  formatted = formatted.replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, (match, content) => {
    // Skip if it looks like currency (contains only numbers, commas, dots)
    if (/^[\d,.\s]+$/.test(content.trim())) {
      return match;
    }
    console.log('Found inline math $:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  // Handle LaTeX delimiters with backslashes
  // Inline math: \( ... \)
  formatted = formatted.replace(/\\\(([^)]+)\\\)/g, (match, content) => {
    console.log('Found LaTeX inline math:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  // Display math: \[ ... \]
  formatted = formatted.replace(/\\\[([^\]]+)\\\]/g, (match, content) => {
    console.log('Found LaTeX display math:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  // Handle HTML-escaped backslashes
  formatted = formatted.replace(/&#92;\(([^)]+)\&#92;\)/g, (match, content) => {
    console.log('Found HTML-escaped inline math:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  formatted = formatted.replace(/&#92;\[([^\]]+)\&#92;\]/g, (match, content) => {
    console.log('Found HTML-escaped display math:', match, 'content:', content);
    const processedContent = processMathContent(content);
    return `<div class="math-formula display">${processedContent}</div>`;
  });
  
  console.log('After LaTeX processing:', formatted);
  
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
  console.log('Processing math content:', content);
  
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
  
  console.log('Processed math content:', processed);
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
      button.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>';
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
      button.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>';
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
