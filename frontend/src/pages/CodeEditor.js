import React, { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { 
  Play, 
  Save, 
  FileText, 
  Code2, 
  Bug, 
  Search,
  Lightbulb,
  RefreshCw
} from 'lucide-react';
import { ApiService } from '../services/api';
import toast from 'react-hot-toast';

const CodeEditor = () => {
  const [code, setCode] = useState('');
  const [language, setLanguage] = useState('python');
  const [fileName, setFileName] = useState('untitled.py');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

  const languages = [
    { value: 'python', label: 'Python', extension: '.py' },
    { value: 'javascript', label: 'JavaScript', extension: '.js' },
    { value: 'typescript', label: 'TypeScript', extension: '.ts' },
    { value: 'java', label: 'Java', extension: '.java' },
    { value: 'cpp', label: 'C++', extension: '.cpp' },
    { value: 'go', label: 'Go', extension: '.go' },
    { value: 'rust', label: 'Rust', extension: '.rs' },
    { value: 'html', label: 'HTML', extension: '.html' },
    { value: 'css', label: 'CSS', extension: '.css' },
    { value: 'json', label: 'JSON', extension: '.json' },
    { value: 'yaml', label: 'YAML', extension: '.yaml' },
  ];

  useEffect(() => {
    // Set default code based on language
    setDefaultCode();
  }, [language]);

  const setDefaultCode = () => {
    const defaultCodes = {
      python: `# Python code
def hello_world():
    print("Hello, World!")

if __name__ == "__main__":
    hello_world()`,
      javascript: `// JavaScript code
function helloWorld() {
    console.log("Hello, World!");
}

helloWorld();`,
      typescript: `// TypeScript code
function helloWorld(): void {
    console.log("Hello, World!");
}

helloWorld();`,
      java: `// Java code
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}`,
      cpp: `// C++ code
#include <iostream>

int main() {
    std::cout << "Hello, World!" << std::endl;
    return 0;
}`,
      go: `// Go code
package main

import "fmt"

func main() {
    fmt.Println("Hello, World!")
}`,
      rust: `// Rust code
fn main() {
    println!("Hello, World!");
}`,
      html: `<!DOCTYPE html>
<html>
<head>
    <title>Hello World</title>
</head>
<body>
    <h1>Hello, World!</h1>
</body>
</html>`,
      css: `/* CSS code */
body {
    font-family: Arial, sans-serif;
    background-color: #f0f0f0;
}

h1 {
    color: #333;
    text-align: center;
}`,
      json: `{
  "name": "Hello World",
  "version": "1.0.0",
  "description": "A simple JSON example"
}`,
      yaml: `# YAML example
name: Hello World
version: 1.0.0
description: A simple YAML example
features:
  - offline
  - ai-powered
  - code-assistant`
    };

    setCode(defaultCodes[language] || '');
    const selectedLang = languages.find(lang => lang.value === language);
    setFileName(`untitled${selectedLang?.extension || '.txt'}`);
  };

  const handleLanguageChange = (newLanguage) => {
    setLanguage(newLanguage);
  };

  const handleCodeChange = (value) => {
    setCode(value || '');
  };

  const handleSave = async () => {
    try {
      await ApiService.writeFile(fileName, code);
      toast.success('File saved successfully');
    } catch (error) {
      console.error('Error saving file:', error);
      toast.error('Failed to save file');
    }
  };

  const handleAnalyze = async () => {
    if (!code.trim()) {
      toast.error('No code to analyze');
      return;
    }

    setIsAnalyzing(true);
    try {
      // First save the code to a temporary file
      const tempFileName = `temp_${Date.now()}.${language}`;
      await ApiService.writeFile(tempFileName, code);
      
      // Then analyze it
      const response = await ApiService.analyzeCode(tempFileName);
      setAnalysis(response);
      
      // Clean up temp file
      await ApiService.deleteFile(tempFileName);
      
      toast.success('Code analysis completed');
    } catch (error) {
      console.error('Error analyzing code:', error);
      toast.error('Failed to analyze code');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;

    setIsSearching(true);
    try {
      const response = await ApiService.searchCode(searchQuery, '.', language, 10);
      setSearchResults(response);
      toast.success(`Found ${response.length} results`);
    } catch (error) {
      console.error('Error searching code:', error);
      toast.error('Failed to search code');
    } finally {
      setIsSearching(false);
    }
  };

  const handleGenerateCode = async () => {
    const prompt = window.prompt('Describe the code you want to generate:');
    if (!prompt) return;

    setIsGenerating(true);
    try {
      const response = await ApiService.generateCode(prompt, language, { current_code: code });
      setCode(response.generated_code);
      toast.success('Code generated successfully');
    } catch (error) {
      console.error('Error generating code:', error);
      toast.error('Failed to generate code. Please check your connection and try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const getLanguageIcon = (lang) => {
    const icons = {
      python: '🐍',
      javascript: '🟨',
      typescript: '🔷',
      java: '☕',
      cpp: '⚡',
      go: '🐹',
      rust: '🦀',
      html: '🌐',
      css: '🎨',
      json: '📄',
      yaml: '📝'
    };
    return icons[lang] || '📄';
  };

  return (
    <div className="flex h-full bg-dark-900">
      {/* Main Editor */}
      <div className="flex-1 flex flex-col">
        {/* Toolbar */}
        <div className="p-4 border-b border-dark-700 bg-dark-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                <span className="text-sm text-dark-400">Language:</span>
                <select
                  value={language}
                  onChange={(e) => handleLanguageChange(e.target.value)}
                  className="px-3 py-1 bg-dark-700 border border-dark-600 rounded text-dark-100 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  {languages.map((lang) => (
                    <option key={lang.value} value={lang.value}>
                      {getLanguageIcon(lang.value)} {lang.label}
                    </option>
                  ))}
                </select>
              </div>
              
              <div className="flex items-center space-x-2">
                <span className="text-sm text-dark-400">File:</span>
                <input
                  type="text"
                  value={fileName}
                  onChange={(e) => setFileName(e.target.value)}
                  className="px-3 py-1 bg-dark-700 border border-dark-600 rounded text-dark-100 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={handleGenerateCode}
                disabled={isGenerating}
                className="flex items-center space-x-2 px-3 py-1 bg-primary-600 hover:bg-primary-700 text-white rounded text-sm transition-colors disabled:opacity-50"
              >
                {isGenerating ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Lightbulb className="w-4 h-4" />
                )}
                <span>{isGenerating ? 'Generating...' : 'Generate'}</span>
              </button>
              
              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing}
                className="flex items-center space-x-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm transition-colors disabled:opacity-50"
              >
                {isAnalyzing ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Code2 className="w-4 h-4" />
                )}
                <span>Analyze</span>
              </button>
              
              <button
                onClick={handleSave}
                className="flex items-center space-x-2 px-3 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-sm transition-colors"
              >
                <Save className="w-4 h-4" />
                <span>Save</span>
              </button>
            </div>
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1">
          <Editor
            height="100%"
            language={language}
            value={code}
            onChange={handleCodeChange}
            theme="vs-dark"
            options={{
              fontSize: 14,
              fontFamily: 'JetBrains Mono, Fira Code, Monaco, Consolas, monospace',
              minimap: { enabled: true },
              wordWrap: 'on',
              lineNumbers: 'on',
              renderWhitespace: 'selection',
              cursorBlinking: 'smooth',
              cursorSmoothCaretAnimation: true,
              smoothScrolling: true,
              contextmenu: true,
              mouseWheelZoom: true,
              automaticLayout: true,
            }}
          />
        </div>
      </div>

      {/* Sidebar */}
      <div className="w-80 border-l border-dark-700 flex flex-col">
        {/* Search */}
        <div className="p-4 border-b border-dark-700 bg-dark-800">
          <h3 className="text-lg font-semibold text-dark-50 mb-3">Code Search</h3>
          <div className="flex space-x-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search in codebase..."
              className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded text-sm text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
            <button
              onClick={handleSearch}
              disabled={isSearching}
              className="px-3 py-2 bg-dark-700 border border-dark-600 rounded hover:bg-dark-600 transition-colors disabled:opacity-50"
            >
              {isSearching ? (
                <RefreshCw className="w-4 h-4 animate-spin text-primary-500" />
              ) : (
                <Search className="w-4 h-4 text-dark-300" />
              )}
            </button>
          </div>
        </div>

        {/* Analysis Results */}
        {analysis && (
          <div className="p-4 border-b border-dark-700">
            <h3 className="text-lg font-semibold text-dark-50 mb-3">Analysis</h3>
            <div className="space-y-3">
              <div className="bg-dark-800 rounded-lg p-3">
                <div className="text-sm text-dark-300 mb-2">Complexity Score</div>
                <div className="text-2xl font-bold text-primary-500">
                  {analysis.complexity_score.toFixed(1)}/10
                </div>
              </div>
              
              <div className="bg-dark-800 rounded-lg p-3">
                <div className="text-sm text-dark-300 mb-2">Functions</div>
                <div className="text-lg font-semibold text-green-500">
                  {analysis.functions.length}
                </div>
              </div>
              
              <div className="bg-dark-800 rounded-lg p-3">
                <div className="text-sm text-dark-300 mb-2">Classes</div>
                <div className="text-lg font-semibold text-blue-500">
                  {analysis.classes.length}
                </div>
              </div>
              
              {analysis.issues.length > 0 && (
                <div className="bg-dark-800 rounded-lg p-3">
                  <div className="text-sm text-dark-300 mb-2">Issues</div>
                  <div className="space-y-1">
                    {analysis.issues.slice(0, 3).map((issue, index) => (
                      <div key={index} className="text-xs text-yellow-400">
                        Line {issue.line_number}: {issue.message}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Search Results */}
        {searchResults.length > 0 && (
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-lg font-semibold text-dark-50 mb-3">Search Results</h3>
            <div className="space-y-2">
              {searchResults.map((result, index) => (
                <div key={index} className="bg-dark-800 rounded-lg p-3">
                  <div className="text-sm font-medium text-primary-500 mb-1">
                    {result.file_path.split('/').pop()}:{result.line_number}
                  </div>
                  <div className="text-xs text-dark-300 font-mono bg-dark-700 p-2 rounded">
                    {result.content}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Functions and Classes */}
        {analysis && (analysis.functions.length > 0 || analysis.classes.length > 0) && (
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-lg font-semibold text-dark-50 mb-3">Structure</h3>
            
            {analysis.functions.length > 0 && (
              <div className="mb-4">
                <div className="text-sm font-medium text-green-500 mb-2">Functions</div>
                <div className="space-y-1">
                  {analysis.functions.map((func, index) => (
                    <div key={index} className="text-xs text-dark-300 bg-dark-800 p-2 rounded">
                      <div className="font-medium">{func.name}</div>
                      <div className="text-dark-400">Line {func.line_number}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {analysis.classes.length > 0 && (
              <div>
                <div className="text-sm font-medium text-blue-500 mb-2">Classes</div>
                <div className="space-y-1">
                  {analysis.classes.map((cls, index) => (
                    <div key={index} className="text-xs text-dark-300 bg-dark-800 p-2 rounded">
                      <div className="font-medium">{cls.name}</div>
                      <div className="text-dark-400">Line {cls.line_number}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default CodeEditor;
