const NEW_SCRIPT_KEYWORDS = [
  'new script',
  'brand new script',
  'new file',
  'new module',
  'new component',
  'fresh script',
  'fresh file',
  'from scratch',
  'start over',
  'start a new',
  'write a new script',
  'create a new script',
  'generate a new script',
  'build a new script',
];

const NEW_SCRIPT_PATTERNS = [
  /(create|build|write|generate)\s+(?:a\s+)?(?:brand\s+new\s+|new\s+)?(?:python|js|javascript|typescript|bash|shell|powershell|go|rust|c#|c\+\+|node|react|vue|script)?\s*script/,
  /(start|spin up|kick off)\s+(?:a\s+)?(?:brand\s+new\s+|new\s+)?project/,
  /(need|want)\s+(?:a\s+)?(?:brand\s+new\s+|new\s+)?script/,
  /make\s+(?:a\s+)?(?:brand\s+new\s+|new\s+)?script/,
];

export const detectNewScriptIntent = (text = '') => {
  const normalized = (text || '').toLowerCase();
  if (!normalized.trim()) {
    return false;
  }

  if (NEW_SCRIPT_KEYWORDS.some((keyword) => normalized.includes(keyword))) {
    return true;
  }

  return NEW_SCRIPT_PATTERNS.some((pattern) => pattern.test(normalized));
};

export default detectNewScriptIntent;

