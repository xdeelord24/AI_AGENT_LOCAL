"""
Code Analyzer Service for Offline AI Agent
Handles code analysis, generation, and search
"""

import os
import re
import ast
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import json


class CodeAnalyzer:
    """Service for code analysis and generation"""
    
    def __init__(self):
        self.supported_languages = {
            'python': {'extensions': ['.py'], 'parser': self._parse_python},
            'javascript': {'extensions': ['.js'], 'parser': self._parse_javascript},
            'typescript': {'extensions': ['.ts', '.tsx'], 'parser': self._parse_typescript},
            'java': {'extensions': ['.java'], 'parser': self._parse_java},
            'cpp': {'extensions': ['.cpp', '.c', '.h', '.hpp'], 'parser': self._parse_cpp},
            'go': {'extensions': ['.go'], 'parser': self._parse_go},
            'rust': {'extensions': ['.rs'], 'parser': self._parse_rust},
            'html': {'extensions': ['.html', '.htm'], 'parser': self._parse_html},
            'css': {'extensions': ['.css'], 'parser': self._parse_css},
            'json': {'extensions': ['.json'], 'parser': self._parse_json},
            'yaml': {'extensions': ['.yaml', '.yml'], 'parser': self._parse_yaml}
        }
    
    async def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """Analyze a code file and extract information"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Detect language
            language = self._detect_language(file_path)
            
            # Parse the code
            parser = self.supported_languages.get(language, {}).get('parser')
            if parser:
                parsed_data = parser(content)
            else:
                parsed_data = self._generic_parse(content)
            
            # Calculate complexity
            complexity_score = self._calculate_complexity(content, language)
            
            # Find potential issues
            issues = self._find_issues(content, language)
            
            return {
                "file_path": file_path,
                "language": language,
                "functions": parsed_data.get("functions", []),
                "classes": parsed_data.get("classes", []),
                "imports": parsed_data.get("imports", []),
                "complexity_score": complexity_score,
                "issues": issues,
                "line_count": len(content.splitlines()),
                "character_count": len(content)
            }
            
        except Exception as e:
            raise Exception(f"Error analyzing file {file_path}: {str(e)}")
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        extension = os.path.splitext(file_path)[1].lower()
        
        for lang, info in self.supported_languages.items():
            if extension in info['extensions']:
                return lang
        
        return 'unknown'
    
    def _parse_python(self, content: str) -> Dict[str, Any]:
        """Parse Python code"""
        try:
            tree = ast.parse(content)
            
            functions = []
            classes = []
            imports = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append({
                        "name": node.name,
                        "line_number": node.lineno,
                        "args": [arg.arg for arg in node.args.args],
                        "docstring": ast.get_docstring(node)
                    })
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        "name": node.name,
                        "line_number": node.lineno,
                        "bases": [base.id if hasattr(base, 'id') else str(base) for base in node.bases],
                        "docstring": ast.get_docstring(node)
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        imports.extend([alias.name for alias in node.names])
                    else:
                        module = node.module or ""
                        imports.extend([f"{module}.{alias.name}" for alias in node.names])
            
            return {
                "functions": functions,
                "classes": classes,
                "imports": imports
            }
        except SyntaxError:
            return {"functions": [], "classes": [], "imports": []}
    
    def _parse_javascript(self, content: str) -> Dict[str, Any]:
        """Parse JavaScript code"""
        functions = []
        classes = []
        imports = []
        
        # Find function declarations
        func_pattern = r'function\s+(\w+)\s*\([^)]*\)'
        for match in re.finditer(func_pattern, content):
            functions.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1,
                "type": "function"
            })
        
        # Find arrow functions
        arrow_pattern = r'(\w+)\s*=\s*\([^)]*\)\s*=>'
        for match in re.finditer(arrow_pattern, content):
            functions.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1,
                "type": "arrow_function"
            })
        
        # Find class declarations
        class_pattern = r'class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            classes.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1
            })
        
        # Find imports
        import_pattern = r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(import_pattern, content):
            imports.append(match.group(1))
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _parse_typescript(self, content: str) -> Dict[str, Any]:
        """Parse TypeScript code (similar to JavaScript but with types)"""
        # For now, use JavaScript parser
        return self._parse_javascript(content)
    
    def _parse_java(self, content: str) -> Dict[str, Any]:
        """Parse Java code"""
        functions = []
        classes = []
        imports = []
        
        # Find method declarations
        method_pattern = r'(public|private|protected)?\s*(static)?\s*(\w+)\s+(\w+)\s*\([^)]*\)'
        for match in re.finditer(method_pattern, content):
            functions.append({
                "name": match.group(4),
                "line_number": content[:match.start()].count('\n') + 1,
                "return_type": match.group(3),
                "modifiers": [m for m in [match.group(1), match.group(2)] if m]
            })
        
        # Find class declarations
        class_pattern = r'class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            classes.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1
            })
        
        # Find imports
        import_pattern = r'import\s+([^;]+);'
        for match in re.finditer(import_pattern, content):
            imports.append(match.group(1).strip())
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _parse_cpp(self, content: str) -> Dict[str, Any]:
        """Parse C++ code"""
        functions = []
        classes = []
        imports = []
        
        # Find function declarations
        func_pattern = r'(\w+)\s+(\w+)\s*\([^)]*\)\s*{'
        for match in re.finditer(func_pattern, content):
            functions.append({
                "name": match.group(2),
                "line_number": content[:match.start()].count('\n') + 1,
                "return_type": match.group(1)
            })
        
        # Find class declarations
        class_pattern = r'class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            classes.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1
            })
        
        # Find includes
        include_pattern = r'#include\s*[<"]([^>"]+)[>"]'
        for match in re.finditer(include_pattern, content):
            imports.append(match.group(1))
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _parse_go(self, content: str) -> Dict[str, Any]:
        """Parse Go code"""
        functions = []
        classes = []
        imports = []
        
        # Find function declarations
        func_pattern = r'func\s+(\w+)\s*\([^)]*\)'
        for match in re.finditer(func_pattern, content):
            functions.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1
            })
        
        # Find struct declarations
        struct_pattern = r'type\s+(\w+)\s+struct'
        for match in re.finditer(struct_pattern, content):
            classes.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1,
                "type": "struct"
            })
        
        # Find imports
        import_pattern = r'import\s+[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(import_pattern, content):
            imports.append(match.group(1))
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _parse_rust(self, content: str) -> Dict[str, Any]:
        """Parse Rust code"""
        functions = []
        classes = []
        imports = []
        
        # Find function declarations
        func_pattern = r'fn\s+(\w+)\s*\([^)]*\)'
        for match in re.finditer(func_pattern, content):
            functions.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1
            })
        
        # Find struct declarations
        struct_pattern = r'struct\s+(\w+)'
        for match in re.finditer(struct_pattern, content):
            classes.append({
                "name": match.group(1),
                "line_number": content[:match.start()].count('\n') + 1,
                "type": "struct"
            })
        
        # Find use statements
        use_pattern = r'use\s+([^;]+);'
        for match in re.finditer(use_pattern, content):
            imports.append(match.group(1).strip())
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _parse_html(self, content: str) -> Dict[str, Any]:
        """Parse HTML code"""
        # Extract script and style tags
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        styles = re.findall(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)
        
        return {
            "functions": [],
            "classes": [],
            "imports": [],
            "scripts": len(scripts),
            "styles": len(styles)
        }
    
    def _parse_css(self, content: str) -> Dict[str, Any]:
        """Parse CSS code"""
        selectors = re.findall(r'([.#]?\w+[^{]*)\s*{', content)
        
        return {
            "functions": [],
            "classes": [],
            "imports": [],
            "selectors": [s.strip() for s in selectors]
        }
    
    def _parse_json(self, content: str) -> Dict[str, Any]:
        """Parse JSON code"""
        try:
            data = json.loads(content)
            return {
                "functions": [],
                "classes": [],
                "imports": [],
                "keys": list(data.keys()) if isinstance(data, dict) else []
            }
        except json.JSONDecodeError:
            return {"functions": [], "classes": [], "imports": []}
    
    def _parse_yaml(self, content: str) -> Dict[str, Any]:
        """Parse YAML code"""
        # Simple YAML parsing - just count top-level keys
        lines = content.split('\n')
        keys = []
        for line in lines:
            if ':' in line and not line.strip().startswith('#'):
                key = line.split(':')[0].strip()
                if key and not key.startswith('-'):
                    keys.append(key)
        
        return {
            "functions": [],
            "classes": [],
            "imports": [],
            "keys": keys
        }
    
    def _generic_parse(self, content: str) -> Dict[str, Any]:
        """Generic parsing for unknown languages"""
        # Count basic patterns
        lines = content.split('\n')
        functions = []
        classes = []
        imports = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Look for function-like patterns
            if re.search(r'\w+\s*\([^)]*\)\s*{?', line):
                functions.append({
                    "name": f"function_{i}",
                    "line_number": i + 1,
                    "type": "generic"
                })
            
            # Look for class-like patterns
            if re.search(r'class\s+\w+', line):
                classes.append({
                    "name": f"class_{i}",
                    "line_number": i + 1,
                    "type": "generic"
                })
        
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }
    
    def _calculate_complexity(self, content: str, language: str) -> float:
        """Calculate code complexity score"""
        lines = content.split('\n')
        non_empty_lines = [line for line in lines if line.strip()]
        
        if not non_empty_lines:
            return 0.0
        
        # Basic complexity factors
        complexity = 0.0
        
        # Cyclomatic complexity indicators
        complexity += content.count('if ') * 1.0
        complexity += content.count('elif ') * 1.0
        complexity += content.count('else:') * 1.0
        complexity += content.count('for ') * 1.0
        complexity += content.count('while ') * 1.0
        complexity += content.count('switch ') * 1.0
        complexity += content.count('case ') * 0.5
        complexity += content.count('try:') * 1.0
        complexity += content.count('except') * 1.0
        complexity += content.count('&&') * 0.5
        complexity += content.count('||') * 0.5
        
        # Normalize by line count
        return min(complexity / len(non_empty_lines) * 10, 10.0)
    
    def _find_issues(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Find potential code issues"""
        issues = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            line_num = i + 1
            line_stripped = line.strip()
            
            # Common issues
            if len(line) > 120:
                issues.append({
                    "type": "style",
                    "severity": "warning",
                    "message": "Line too long (>120 characters)",
                    "line_number": line_num
                })
            
            if line_stripped.endswith(';') and language == 'python':
                issues.append({
                    "type": "syntax",
                    "severity": "warning",
                    "message": "Unnecessary semicolon in Python",
                    "line_number": line_num
                })
            
            if 'TODO' in line_stripped or 'FIXME' in line_stripped:
                issues.append({
                    "type": "todo",
                    "severity": "info",
                    "message": line_stripped,
                    "line_number": line_num
                })
            
            if 'print(' in line_stripped and language == 'python':
                issues.append({
                    "type": "style",
                    "severity": "info",
                    "message": "Consider using logging instead of print",
                    "line_number": line_num
                })
        
        return issues
    
    def _extract_code_from_response(self, response: str, language: str) -> str:
        """Extract clean code from AI response"""
        import re
        
        # Remove common prefixes and suffixes
        response = response.strip()
        
        # First, try to extract code from markdown code blocks
        # Pattern: ```language\ncode\n```
        code_block_pattern = rf'```{re.escape(language)}\s*\n(.*?)\n```'
        match = re.search(code_block_pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Pattern: ```\ncode\n```
        code_block_pattern = r'```\s*\n(.*?)\n```'
        match = re.search(code_block_pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Pattern: ```language code ``` (single line or multiline)
        code_block_pattern = rf'```{re.escape(language)}\s*(.*?)```'
        match = re.search(code_block_pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Pattern: ``` code ``` (generic)
        code_block_pattern = r'```\s*(.*?)```'
        match = re.search(code_block_pattern, response, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Remove markdown code blocks if present at start/end
        if response.startswith(f"```{language}"):
            response = response[len(f"```{language}"):].strip()
            if response.startswith('\n'):
                response = response[1:]
        elif response.startswith("```"):
            response = response[3:].strip()
            if response.startswith('\n'):
                response = response[1:]
        
        if response.endswith("```"):
            response = response[:-3].strip()
            if response.endswith('\n'):
                response = response[:-1]
        
        # Remove common AI response patterns
        patterns_to_remove = [
            "Here's the code:",
            "Here is the code:",
            "Here's a solution:",
            "Here is a solution:",
            "Here's the implementation:",
            "Here is the implementation:",
            "Here's the complete code:",
            "Here is the complete code:",
            "Here's the Python code:",
            "Here is the Python code:",
            "Here's the JavaScript code:",
            "Here is the JavaScript code:",
            "Here's the Java code:",
            "Here is the Java code:",
            "Here's the C++ code:",
            "Here is the C++ code:",
            "Here's the Go code:",
            "Here is the Go code:",
            "Here's the Rust code:",
            "Here is the Rust code:",
        ]
        
        for pattern in patterns_to_remove:
            if response.startswith(pattern):
                response = response[len(pattern):].strip()
        
        # Clean up any remaining text before the actual code
        lines = response.split('\n')
        code_lines = []
        in_code = False
        
        for line in lines:
            # Skip empty lines at the beginning
            if not in_code and not line.strip():
                continue
            
            # Start collecting code when we see actual code patterns
            if not in_code:
                # Look for common code patterns
                if (line.strip().startswith(('#', '//', '/*', 'import ', 'from ', 'def ', 'function ', 'class ', 'public ', 'private ', 'const ', 'let ', 'var ', '#include', 'package ', 'use ')) or
                    line.strip().endswith((':', '{', ';')) or
                    line.strip() in ['{', '}', ']', '['] or
                    any(keyword in line for keyword in ['def ', 'function ', 'class ', 'import ', 'from ', 'const ', 'let ', 'var ', 'public ', 'private ', 'protected '])):
                    in_code = True
            
            if in_code:
                code_lines.append(line)
        
        # If we didn't find any code patterns, return the original response
        if not code_lines:
            return response
        
        return '\n'.join(code_lines)
    
    async def generate_code(
        self, 
        prompt: str, 
        language: str = "python",
        context: Dict[str, Any] = None,
        max_length: int = 1000,
        ai_service = None
    ) -> Dict[str, Any]:
        """Generate code based on a prompt"""
        # Import AI service here to avoid circular imports
        from .ai_service import AIService
        
        # Use provided AI service or create a new one
        if ai_service is None:
            ai_service = AIService()
        
        # Check if AI service is available
        try:
            is_connected = await ai_service.check_ollama_connection()
            if not is_connected:
                raise Exception("Ollama is not running. Please start Ollama and install a model.")
        except Exception as e:
            error_msg = str(e)
            print(f"❌ AI Service Error: {error_msg}")
            raise Exception(f"AI service unavailable: {error_msg}. Please ensure Ollama is running.")
        
        try:
            # Build a comprehensive prompt for code generation
            code_prompt = f"""You are an expert {language} programmer. Generate complete, working code based on the following request.

Request: {prompt}

Requirements:
- Write complete, functional {language} code
- The code should be ready to run without modifications
- Include proper comments and documentation within the code
- Follow {language} best practices and conventions
- Include error handling where appropriate
- Make the code production-ready

{f"Additional Context: {json.dumps(context, indent=2)}" if context else ""}

Generate the complete {language} code implementation:"""
            
            # Get AI response
            response = await ai_service._call_ollama(code_prompt)
            
            if not response or len(response.strip()) == 0:
                raise Exception("Empty response from AI service")
            
            # Clean up the response to extract just the code
            generated_code = self._extract_code_from_response(response, language)
            
            # If the extracted code is still empty, use the raw response
            if not generated_code or generated_code.strip() == "":
                generated_code = response.strip()
            
            # Generate explanation
            explanation = f"Generated {language} code based on the prompt: '{prompt}'. The code includes proper structure, documentation, and follows {language} best practices."
            
            return {
                "generated_code": generated_code,
                "explanation": explanation,
                "language": language,
                "confidence": 0.9
            }
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Code Generation Error: {error_msg}")
            # Re-raise the exception so the API can handle it properly
            raise Exception(f"Error generating code: {error_msg}")
    
    async def search_code(
        self, 
        query: str, 
        path: str = ".",
        language: Optional[str] = None,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for code patterns"""
        results = []
        
        for root, dirs, files in os.walk(path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                if language and not file.endswith(tuple(self.supported_languages[language]['extensions'])):
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if query.lower() in line.lower():
                            # Get context (3 lines before and after)
                            start = max(0, i - 3)
                            end = min(len(lines), i + 4)
                            context_lines = lines[start:end]
                            
                            results.append({
                                "file_path": file_path,
                                "line_number": i + 1,
                                "content": line.strip(),
                                "context": '\n'.join(context_lines),
                                "relevance_score": 0.8  # Simple scoring
                            })
                            
                            if len(results) >= max_results:
                                return results
                
                except (OSError, UnicodeDecodeError):
                    continue
        
        return results
    
    async def get_supported_languages(self) -> List[str]:
        """Get list of supported programming languages"""
        return list(self.supported_languages.keys())
    
    async def refactor_code(self, file_path: str, refactor_type: str) -> Dict[str, Any]:
        """Refactor code in a specific way"""
        # This would integrate with the AI service for intelligent refactoring
        return {
            "message": f"Refactoring {refactor_type} not yet implemented",
            "original_file": file_path,
            "refactored_code": None
        }
    
    async def get_suggestions(self, file_path: str, line_number: int) -> List[Dict[str, Any]]:
        """Get code suggestions for a specific line"""
        # This would provide intelligent suggestions based on context
        return [
            {
                "type": "completion",
                "suggestion": "Add error handling",
                "confidence": 0.7
            },
            {
                "type": "optimization",
                "suggestion": "Consider using list comprehension",
                "confidence": 0.6
            }
        ]
