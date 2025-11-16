import React, { useState, useEffect } from 'react';
import { 
  Folder, 
  File, 
  ChevronRight, 
  ChevronDown, 
  Search, 
  Plus, 
  Trash2,
  Eye,
  Edit3,
  Download
} from 'lucide-react';
import { ApiService } from '../services/api';
import toast from 'react-hot-toast';

const FileExplorer = () => {
  const [currentPath, setCurrentPath] = useState('.');
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFolders, setExpandedFolders] = useState(new Set());
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newItemName, setNewItemName] = useState('');
  const [newItemType, setNewItemType] = useState('file');

  useEffect(() => {
    loadDirectory(currentPath);
  }, [currentPath]);

  const loadDirectory = async (path) => {
    setLoading(true);
    try {
      const response = await ApiService.listDirectory(path);
      setFiles(response.files || []);
    } catch (error) {
      console.error('Error loading directory:', error);
      toast.error('Failed to load directory');
    } finally {
      setLoading(false);
    }
  };

  const loadFile = async (filePath) => {
    try {
      const response = await ApiService.readFile(filePath);
      setFileContent(response.content);
      setSelectedFile(filePath);
    } catch (error) {
      console.error('Error loading file:', error);
      toast.error('Failed to load file');
    }
  };

  const handleFileClick = async (file) => {
    if (file.is_directory) {
      const newPath = file.path;
      setCurrentPath(newPath);
      setExpandedFolders(prev => new Set([...prev, newPath]));
    } else {
      await loadFile(file.path);
    }
  };

  const handleBack = () => {
    const parentPath = currentPath.split('/').slice(0, -1).join('/') || '.';
    setCurrentPath(parentPath);
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    
    setLoading(true);
    try {
      const response = await ApiService.searchFiles(searchQuery, currentPath);
      setFiles(response.results || []);
    } catch (error) {
      console.error('Error searching files:', error);
      toast.error('Failed to search files');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateItem = async () => {
    if (!newItemName.trim()) return;

    try {
      const fullPath = `${currentPath}/${newItemName}`.replace('//', '/');
      
      if (newItemType === 'directory') {
        await ApiService.createDirectory(fullPath);
        toast.success('Directory created successfully');
      } else {
        await ApiService.writeFile(fullPath, '');
        toast.success('File created successfully');
      }
      
      setShowCreateDialog(false);
      setNewItemName('');
      loadDirectory(currentPath);
    } catch (error) {
      console.error('Error creating item:', error);
      toast.error('Failed to create item');
    }
  };

  const handleDeleteItem = async (filePath) => {
    if (!window.confirm('Are you sure you want to delete this item?')) return;

    try {
      await ApiService.deleteFile(filePath);
      toast.success('Item deleted successfully');
      loadDirectory(currentPath);
      if (selectedFile === filePath) {
        setSelectedFile(null);
        setFileContent('');
      }
    } catch (error) {
      console.error('Error deleting item:', error);
      toast.error('Failed to delete item');
    }
  };

  const getFileIcon = (file) => {
    if (file.is_directory) {
      return <Folder className="w-5 h-5 text-blue-400" />;
    }
    
    const extension = file.extension?.toLowerCase();
    const iconClass = "w-5 h-5";
    
    switch (extension) {
      case '.py':
        return <File className={`${iconClass} text-yellow-400`} />;
      case '.js':
      case '.jsx':
        return <File className={`${iconClass} text-yellow-300`} />;
      case '.ts':
      case '.tsx':
        return <File className={`${iconClass} text-blue-300`} />;
      case '.html':
        return <File className={`${iconClass} text-orange-400`} />;
      case '.css':
        return <File className={`${iconClass} text-blue-400`} />;
      case '.json':
        return <File className={`${iconClass} text-green-400`} />;
      case '.md':
        return <File className={`${iconClass} text-gray-400`} />;
      default:
        return <File className={`${iconClass} text-gray-500`} />;
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  return (
    <div className="flex h-full bg-dark-900">
      {/* File Tree */}
      <div className="w-1/2 border-r border-dark-700 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-dark-700 bg-dark-800">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-dark-50">File Explorer</h2>
            <button
              onClick={() => setShowCreateDialog(true)}
              className="p-2 bg-primary-600 hover:bg-primary-700 rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4 text-white" />
            </button>
          </div>
          
          {/* Search */}
          <div className="flex space-x-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search files..."
              className="flex-1 px-3 py-2 bg-dark-700 border border-dark-600 rounded text-sm text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
            <button
              onClick={handleSearch}
              className="px-3 py-2 bg-dark-700 border border-dark-600 rounded hover:bg-dark-600 transition-colors"
            >
              <Search className="w-4 h-4 text-dark-300" />
            </button>
          </div>
        </div>

        {/* Breadcrumb */}
        <div className="p-3 border-b border-dark-700 bg-dark-800">
          <div className="flex items-center space-x-2 text-sm">
            <button
              onClick={handleBack}
              className="text-primary-500 hover:text-primary-400 transition-colors"
            >
              ← Back
            </button>
            <span className="text-dark-400">/</span>
            <span className="text-dark-300 font-mono">{currentPath}</span>
          </div>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
          ) : (
            <div className="space-y-1">
              {files.map((file) => (
                <div
                  key={file.path}
                  className={`flex items-center space-x-3 p-2 rounded hover:bg-dark-700 cursor-pointer transition-colors ${
                    selectedFile === file.path ? 'bg-dark-700' : ''
                  }`}
                  onClick={() => handleFileClick(file)}
                >
                  {getFileIcon(file)}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-dark-100 truncate">
                      {file.name}
                    </div>
                    <div className="text-xs text-dark-400">
                      {file.is_directory ? 'Directory' : formatFileSize(file.size)}
                    </div>
                  </div>
                  <div className="flex items-center space-x-1">
                    {!file.is_directory && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteItem(file.path);
                        }}
                        className="p-1 hover:bg-red-600 rounded transition-colors"
                      >
                        <Trash2 className="w-3 h-3 text-red-400" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* File Content */}
      <div className="w-1/2 flex flex-col">
        {selectedFile ? (
          <>
            <div className="p-4 border-b border-dark-700 bg-dark-800">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-dark-50 truncate">
                  {selectedFile.split('/').pop()}
                </h3>
                <div className="flex items-center space-x-2">
                  <button className="p-2 hover:bg-dark-700 rounded transition-colors">
                    <Edit3 className="w-4 h-4 text-dark-300" />
                  </button>
                  <button className="p-2 hover:bg-dark-700 rounded transition-colors">
                    <Download className="w-4 h-4 text-dark-300" />
                  </button>
                </div>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <pre className="text-sm text-dark-100 font-mono whitespace-pre-wrap">
                {fileContent}
              </pre>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <Eye className="w-16 h-16 text-dark-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-dark-300 mb-2">
                No file selected
              </h3>
              <p className="text-dark-400">
                Click on a file to view its contents
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-dark-800 border border-dark-700 rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold text-dark-50 mb-4">
              Create New Item
            </h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Type
                </label>
                <select
                  value={newItemType}
                  onChange={(e) => setNewItemType(e.target.value)}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="file">File</option>
                  <option value="directory">Directory</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-dark-300 mb-2">
                  Name
                </label>
                <input
                  type="text"
                  value={newItemName}
                  onChange={(e) => setNewItemName(e.target.value)}
                  placeholder={`Enter ${newItemType} name`}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded text-dark-100 placeholder-dark-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  autoFocus
                />
              </div>
            </div>
            
            <div className="flex justify-end space-x-3 mt-6">
              <button
                onClick={() => setShowCreateDialog(false)}
                className="px-4 py-2 text-dark-300 hover:text-dark-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateItem}
                className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded transition-colors"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default FileExplorer;
