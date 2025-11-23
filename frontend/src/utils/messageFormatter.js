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

/**
 * Build inline HTML for a pair of removed/added lines so that only the
 * changed middle segment is highlighted, instead of the entire tail
 * from the first difference to the end of the line.
 */
const buildInlineDiffHtml = (oldText = '', newText = '') => {
  const oldStr = oldText ?? '';
  const newStr = newText ?? '';

  let start = 0;
  const oldLen = oldStr.length;
  const newLen = newStr.length;

  // Find common prefix
  while (start < oldLen && start < newLen && oldStr[start] === newStr[start]) {
    start += 1;
  }

  let endOld = oldLen - 1;
  let endNew = newLen - 1;

  // Find common suffix, making sure we don't cross the prefix
  while (endOld >= start && endNew >= start && oldStr[endOld] === newStr[endNew]) {
    endOld -= 1;
    endNew -= 1;
  }

  const unchangedPrefix = escapeHtml(oldStr.slice(0, start));
  const unchangedPrefixNew = escapeHtml(newStr.slice(0, start));

  const oldChangedRaw = oldStr.slice(start, endOld + 1);
  const newChangedRaw = newStr.slice(start, endNew + 1);

  const oldChanged = escapeHtml(oldChangedRaw);
  const newChanged = escapeHtml(newChangedRaw);

  const oldSuffix = escapeHtml(oldStr.slice(endOld + 1));
  const newSuffix = escapeHtml(newStr.slice(endNew + 1));

  const oldHtml =
    unchangedPrefix +
    (oldChangedRaw
      ? `<span class="diff-chunk diff-chunk-removed">${oldChanged}</span>`
      : '') +
    oldSuffix;

  const newHtml =
    unchangedPrefixNew +
    (newChangedRaw
      ? `<span class="diff-chunk diff-chunk-added">${newChanged}</span>`
      : '') +
    newSuffix;

  return { oldHtml, newHtml };
};

const ensureRenderer = () => {
  if (rendererInstance) {
    return rendererInstance;
  }

  const renderer = new marked.Renderer();

  renderer.code = ({ text = '', lang = '' } = {}) => {
    const language = (lang || '').split(/\s+/)[0];
    const normalizedLang = normalizeLanguage(language || 'text');
    const rawCode = text.trimEnd();
    const safeRawCode = rawCode.replace(/<\/textarea/gi, '<\\/textarea');

    // Special handling for unified diff / patch blocks so code changes are clearly highlighted.
    if (normalizedLang === 'diff' || normalizedLang === 'patch') {
      const lines = rawCode.split('\n');
      const highlightedLines = [];

      const isRemovedLine = (line = '') =>
        line.length > 0 && line[0] === '-' && !line.startsWith('---');
      const isAddedLine = (line = '') =>
        line.length > 0 && line[0] === '+' && !line.startsWith('+++');
      const isFileMetadataLine = (line = '') =>
        line.startsWith('diff ') ||
        line.startsWith('index ') ||
        line.startsWith('+++ ') ||
        line.startsWith('--- ');
      const isHunkHeader = (line = '') => line.startsWith('@@');

      const renderBasicLine = (line, overrideClass) => {
        const escaped = escapeHtml(line);
        const content = escaped === '' ? '&nbsp;' : escaped;
        const lineClass =
          overrideClass ||
          (() => {
            if (isFileMetadataLine(line)) return 'diff-line-file';
            if (isHunkHeader(line)) return 'diff-line-hunk';
            if (isAddedLine(line)) return 'diff-line-added';
            if (isRemovedLine(line)) return 'diff-line-removed';
            return 'diff-line-context';
          })();
        highlightedLines.push(`<span class="diff-line ${lineClass}">${content}</span>`);
      };

      for (let i = 0; i < lines.length; ) {
        const line = lines[i] ?? '';

        if (isRemovedLine(line)) {
          const removedBlock = [];
          while (i < lines.length && isRemovedLine(lines[i] ?? '')) {
            removedBlock.push((lines[i] ?? '').slice(1));
            i += 1;
          }

          const addedBlock = [];
          let j = i;
          while (j < lines.length && isAddedLine(lines[j] ?? '')) {
            addedBlock.push((lines[j] ?? '').slice(1));
            j += 1;
          }

          if (addedBlock.length > 0) {
            const pairCount = Math.min(removedBlock.length, addedBlock.length);

            for (let k = 0; k < pairCount; k += 1) {
              const oldLineText = removedBlock[k];
              const newLineText = addedBlock[k];
              const { oldHtml, newHtml } = buildInlineDiffHtml(oldLineText, newLineText);
              const removedContent = `<span class="diff-sign">-</span>${
                oldHtml === '' ? '&nbsp;' : oldHtml
              }`;
              const addedContent = `<span class="diff-sign">+</span>${
                newHtml === '' ? '&nbsp;' : newHtml
              }`;

              highlightedLines.push(
                `<span class="diff-line diff-line-removed">${removedContent}</span>`
              );
              highlightedLines.push(
                `<span class="diff-line diff-line-added">${addedContent}</span>`
              );
            }

            if (removedBlock.length > pairCount) {
              for (let k = pairCount; k < removedBlock.length; k += 1) {
                renderBasicLine(`-${removedBlock[k]}`, 'diff-line-removed');
              }
            }

            if (addedBlock.length > pairCount) {
              for (let k = pairCount; k < addedBlock.length; k += 1) {
                renderBasicLine(`+${addedBlock[k]}`, 'diff-line-added');
              }
            }

            i = j;
            continue;
          }

          // No added block follows; render removed lines as-is.
          removedBlock.forEach((text) => {
            renderBasicLine(`-${text}`, 'diff-line-removed');
          });
          continue;
        }

        renderBasicLine(line);
        i += 1;
      }

      const diffHtml = highlightedLines.join('');

      return `<div class="code-block not-prose language-${normalizedLang}" data-language="${normalizedLang}">
        <div class="code-header">
          <span class="code-language">${normalizedLang}</span>
          <button class="copy-code-btn" type="button" title="Copy code" aria-label="Copy code">
            <span class="copy-icon" aria-hidden="true">📋</span>
            <span class="copy-text">Copy</span>
          </button>
        </div>
        <pre><code class="language-${normalizedLang}">${diffHtml}</code></pre>
        <textarea class="code-raw" hidden>${safeRawCode}</textarea>
      </div>`;
    }

    const escapedCode = escapeHtml(rawCode);

    return `<div class="code-block not-prose language-${normalizedLang}" data-language="${normalizedLang}">
      <div class="code-header">
        <span class="code-language">${normalizedLang}</span>
        <button class="copy-code-btn" type="button" title="Copy code" aria-label="Copy code">
          <span class="copy-icon" aria-hidden="true">📋</span>
          <span class="copy-text">Copy</span>
        </button>
      </div>
      <pre><code class="language-${normalizedLang}">${escapedCode}</code></pre>
      <textarea class="code-raw" hidden>${safeRawCode}</textarea>
    </div>`;
  };

  renderer.list = function ({ ordered, start, items } = {}) {
    const tag = ordered ? 'ol' : 'ul';
    const classes = ordered
      ? 'markdown-list markdown-list-ordered'
      : 'markdown-list markdown-list-unordered';
    const startAttr =
      ordered && typeof start === 'number' && start !== 1 ? ` start="${start}"` : '';
    const body = Array.isArray(items)
      ? items.map((item) => this.listitem(item)).join('')
      : '';
    return `<${tag} class="${classes}"${startAttr}>${body}</${tag}>`;
  };

  renderer.listitem = function (token = {}) {
    const inner = this.parser.parse(token.tokens || []);
    if (token.task) {
      return `<li class="task-item markdown-list-item" data-checked="${
        token.checked ? 'x' : ' '
      }">${inner}</li>`;
    }
    return `<li class="markdown-list-item">${inner}</li>`;
  };

  renderer.link = function ({ href, title, tokens } = {}) {
    const safeHref = href || '#';
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
    const text = this.parser.parseInline(tokens || []);
    return `<a href="${safeHref}"${titleAttr} target="_blank" rel="noopener noreferrer" class="markdown-link">${text}</a>`;
  };

  renderer.image = ({ href, title, text } = {}) => {
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
    return `<img src="${href}" alt="${escapeHtml(text || '')}"${titleAttr} class="markdown-image" loading="lazy">`;
  };

  const baseTable = renderer.table.bind(renderer);
  renderer.table = function (token) {
    const html = baseTable(token);
    return html.replace('<table>', '<table class="markdown-table">');
  };

  renderer.text = (token = {}) =>
    formatInlineMarkdown(escapeHtml(token.text ?? ''));

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

export const formatMessageContent = (content, webReferences = null) => {
  const renderer = ensureRenderer();
  let normalized = normalizeInputContent(content).replace(/\r\n/g, '\n');
  
  // Filter out raw JSON structures that might be accidentally included
  // Remove trailing closing brackets/braces that look like JSON artifacts
  normalized = normalized.replace(/[\]}]+(\s*)$/m, '$1');
  
  // Remove JSON object/array structures that appear to be metadata artifacts
  // This regex matches patterns like: }, "fileoperations": [{...}], etc.
  normalized = normalized.replace(/\s*[,\s]*\}\s*,\s*"fileoperations?":\s*\[.*?\]/gis, '');
  normalized = normalized.replace(/\s*[,\s]*\}\s*,\s*"file_operations?":\s*\[.*?\]/gis, '');
  normalized = normalized.replace(/\s*[,\s]*\}\s*,\s*"ai[_\-]?plan":\s*\{.*?\}\s*[,}]?/gis, '');
  normalized = normalized.replace(/\s*[,\s]*\}\s*,\s*"activity[_\-]?log":\s*\[.*?\]/gis, '');
  
  // Remove standalone JSON objects/arrays at the end of content
  // Match JSON-like structures (objects or arrays) that might be metadata
  normalized = normalized.replace(/\s*[,\s]*[{\[]\s*"fileoperations?":\s*\[.*?\]\s*[}\]]/gis, '');
  normalized = normalized.replace(/\s*[,\s]*[{\[]\s*"file_operations?":\s*\[.*?\]\s*[}\]]/gis, '');
  normalized = normalized.replace(/\s*[,\s]*[{\[]\s*"ai[_\-]?plan":\s*\{.*?\}\s*[}\]]/gis, '');
  normalized = normalized.replace(/\s*[,\s]*[{\[]\s*"activity[_\-]?log":\s*\[.*?\]\s*[}\]]/gis, '');
  
  // Remove lines that are just closing brackets or JSON structure markers
  const lines = normalized.split('\n');
  const filteredLines = lines.filter((line, index) => {
    const trimmed = line.trim();
    
    // Skip lines that are only closing brackets/braces
    if (/^[\]}]+$/.test(trimmed)) {
      return false;
    }
    
    // Skip lines that look like JSON structure artifacts
    if (/^\s*[,{\[]\s*$/.test(trimmed)) {
      return false;
    }
    
    // Skip lines that start with JSON keys like "fileoperations", "aiplan", etc.
    if (/^\s*[,{\[]?\s*"fileoperations?":/i.test(trimmed)) {
      return false;
    }
    if (/^\s*[,{\[]?\s*"file_operations?":/i.test(trimmed)) {
      return false;
    }
    if (/^\s*[,{\[]?\s*"ai[_\-]?plan":/i.test(trimmed)) {
      return false;
    }
    if (/^\s*[,{\[]?\s*"activity[_\-]?log":/i.test(trimmed)) {
      return false;
    }
    
    // Skip lines that are just empty JSON objects or arrays
    if (/^\s*[{\[]\s*"type":\s*"none",?\s*$/i.test(trimmed)) {
      return false;
    }
    if (/^\s*"path":\s*"",?\s*$/i.test(trimmed)) {
      return false;
    }
    if (/^\s*"content":\s*"",?\s*$/i.test(trimmed)) {
      return false;
    }
    
    return true;
  });
  
  normalized = filteredLines.join('\n');
  
  // Remove any remaining trailing JSON artifacts
  normalized = normalized.replace(/[,\s]*[\]}]+(\s*)$/m, '$1');
  normalized = normalized.replace(/\s*[,\s]*\}\s*,\s*"fileoperations?":\s*\[/gi, '');
  normalized = normalized.replace(/\s*"type":\s*"none",?\s*/gi, '');
  normalized = normalized.replace(/\s*"path":\s*"",?\s*/gi, '');
  normalized = normalized.replace(/\s*"content":\s*"",?\s*/gi, '');
  
  // Clean up multiple consecutive newlines
  normalized = normalized.replace(/\n{3,}/g, '\n\n').trim();
  
  // Convert reference citations like [1], [2] to markdown links BEFORE markdown parsing
  // This ensures they're properly converted to clickable links
  if (webReferences && Array.isArray(webReferences) && webReferences.length > 0) {
    // Create a map of index to URL for quick lookup
    const refMap = new Map();
    webReferences.forEach(ref => {
      if (ref.index && ref.url) {
        refMap.set(ref.index, {
          url: ref.url,
          title: ref.title || ref.url
        });
      }
    });

    // Replace [1], [2], etc. with markdown link format BEFORE markdown parsing
    // Match [1], [2], [10], etc. but NOT [text](url) - use negative lookahead
    // Process in reverse to avoid offset issues when replacing
    const refPattern = /\[(\d+)\](?!\()/g;
    let match;
    const replacements = [];
    
    // First, collect all matches with their positions
    while ((match = refPattern.exec(normalized)) !== null) {
      const index = parseInt(match[1], 10);
      const ref = refMap.get(index);
      if (ref) {
        // Check if we're inside a code block (simple check)
        const beforeMatch = normalized.substring(0, match.index);
        const codeBlockCount = (beforeMatch.match(/```/g) || []).length;
        const isInCodeBlock = codeBlockCount % 2 !== 0;
        
        // Check if we're inside inline code
        const lastBacktick = beforeMatch.lastIndexOf('`');
        const afterMatch = normalized.substring(match.index + match[0].length);
        const nextBacktick = afterMatch.indexOf('`');
        const isInInlineCode = lastBacktick !== -1 && nextBacktick !== -1 && 
                               !normalized.substring(lastBacktick + 1, match.index + match[0].length + nextBacktick).includes('\n');
        
        if (!isInCodeBlock && !isInInlineCode) {
          replacements.push({
            index: match.index,
            length: match[0].length,
            replacement: `[${index}](${ref.url.replace(/\)/g, '%29')} "${(ref.title || ref.url).replace(/"/g, '&quot;')}")`
          });
        }
      }
    }
    
    // Apply replacements in reverse order to maintain correct indices
    for (let i = replacements.length - 1; i >= 0; i--) {
      const rep = replacements[i];
      normalized = normalized.substring(0, rep.index) + rep.replacement + normalized.substring(rep.index + rep.length);
    }
  }
  
  let formattedContent = '';

  try {
    // Support both marked v4 (function) and v5+ (marked.parse)
    if (typeof marked.parse === 'function') {
      formattedContent = marked.parse(normalized, { renderer });
    } else if (typeof marked === 'function') {
      formattedContent = marked(normalized, { renderer });
    } else {
      formattedContent = '';
    }
  } catch (error) {
    // eslint-disable-next-line no-console
    console.log('formatMessageContent: marked.parse threw, falling back to plain text HTML', {
      error,
      normalized,
    });
    formattedContent = '';
  }

  formattedContent = applyCalloutEnhancements(formattedContent);

  // After markdown parsing, convert reference links to use the reference-link class
  // The markdown parser will have converted [1](url) to <a> tags, but we need to change the class
  if (webReferences && Array.isArray(webReferences) && webReferences.length > 0) {
    const refMap = new Map();
    webReferences.forEach(ref => {
      if (ref.index && ref.url) {
        refMap.set(ref.index, {
          url: ref.url,
          title: ref.title || ref.url
        });
      }
    });

    // Find links that contain [number] as text and match reference URLs
    // Handle various HTML formats that markdown might produce
    formattedContent = formattedContent.replace(
      /<a\s+([^>]*?)href=["']([^"']+)["']([^>]*?)>\[(\d+)\]<\/a>/gi,
      (match, beforeHref, url, afterHref, indexStr) => {
        // Skip if already has reference-link class
        if (match.includes('reference-link')) {
          return match;
        }
        
        const index = parseInt(indexStr, 10);
        const ref = refMap.get(index);
        if (ref) {
          // Decode URL to compare (markdown might escape it)
          let decodedUrl;
          try {
            decodedUrl = decodeURIComponent(url.replace(/%29/g, ')'));
          } catch (e) {
            decodedUrl = url;
          }
          
          // Check if URL matches (handle both encoded and decoded, with or without trailing slash)
          const normalizeUrl = (u) => u.replace(/\/$/, '').toLowerCase();
          if (normalizeUrl(ref.url) === normalizeUrl(decodedUrl) || normalizeUrl(ref.url) === normalizeUrl(url)) {
            const safeUrl = escapeHtml(ref.url);
            const safeTitle = escapeHtml(ref.title);
            return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="reference-link" title="${safeTitle}">[${index}]</a>`;
          }
        }
        return match;
      }
    );
  }

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
  let formatted = typeof text === 'string' ? text : String(text ?? '');
  
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
  formatted = formatted.replace(/&#92;\(([^)]+)&#92;\)/g, (match, content) => {
    const processedContent = processMathContent(content);
    return `<span class="math-formula inline">${processedContent}</span>`;
  });
  
  formatted = formatted.replace(/&#92;\[([^\]]+)&#92;\]/g, (match, content) => {
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
  const safeText = text == null ? '' : String(text);

  if (typeof document !== 'undefined' && document?.createElement) {
    const div = document.createElement('div');
    div.textContent = safeText;
    return div.innerHTML;
  }

  return safeText
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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

export const highlightCodeBlocks = (container = document) => {
  if (typeof window === 'undefined') {
    return;
  }
  
  // Wait for Prism to load if not available yet
  if (!window.Prism) {
    // Try again after a short delay
    setTimeout(() => highlightCodeBlocks(container), 100);
    return;
  }
  
  try {
    const targetContainer = container === document ? document.body : container;
    const codeBlocks = targetContainer.querySelectorAll('pre code[class*="language-"]');
    codeBlocks.forEach((block) => {
      // Only highlight if not already highlighted and not language-none
      const hasLanguage = Array.from(block.classList).some(cls => 
        cls.startsWith('language-') && cls !== 'language-none'
      );
      if (hasLanguage && !block.hasAttribute('data-prism-processed')) {
        try {
          window.Prism.highlightElement(block);
        } catch (err) {
          // If highlighting fails for a specific block, continue with others
          console.warn('Failed to highlight code block:', err);
        }
      }
    });
  } catch (error) {
    console.warn('Failed to highlight code blocks:', error);
  }
};
