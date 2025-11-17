"""
File Service for Offline AI Agent
Handles file system operations
"""

import os
import aiofiles
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import mimetypes
import shutil


class FileInfo:
    """File information model"""
    
    def __init__(self, path: str):
        self.path = path
        self.stat = os.stat(path)
        self.name = os.path.basename(path)
        self.is_directory = os.path.isdir(path)
        self.size = self.stat.st_size
        self.modified_time = datetime.fromtimestamp(self.stat.st_mtime).isoformat()
        self.extension = os.path.splitext(self.name)[1] if not self.is_directory else None


class FileService:
    """Service for file system operations"""
    
    def __init__(self):
        self.current_directory = os.getcwd()
        self.supported_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp',
            '.cs', '.php', '.rb', '.go', '.rs', '.swift', '.kt', '.scala', '.r',
            '.m', '.pl', '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
            '.html', '.css', '.scss', '.sass', '.less', '.xml', '.json', '.yaml',
            '.yml', '.toml', '.ini', '.cfg', '.conf', '.env', '.md', '.txt',
            '.sql', '.dockerfile', '.dockerignore', '.gitignore'
        }
        self.max_tree_children = 400
    
    async def list_directory(self, path: str) -> List[Dict[str, Any]]:
        """List files and directories in the specified path"""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path not found: {path}")
            
            if not os.path.isdir(path):
                raise NotADirectoryError(f"Path is not a directory: {path}")
            
            items = []
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    file_info = FileInfo(item_path)
                    items.append({
                        "name": file_info.name,
                        "path": item_path,
                        "size": file_info.size,
                        "is_directory": file_info.is_directory,
                        "modified_time": file_info.modified_time,
                        "extension": file_info.extension
                    })
                except (OSError, PermissionError):
                    # Skip files we can't access
                    continue
            
            # Sort: directories first, then files, both alphabetically
            items.sort(key=lambda x: (not x["is_directory"], x["name"].lower()))
            return items
            
        except Exception as e:
            raise Exception(f"Error listing directory {path}: {str(e)}")
    
    async def read_file(self, path: str) -> str:
        """Read the content of a file"""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"File not found: {path}")
            
            if os.path.isdir(path):
                raise IsADirectoryError(f"Path is a directory: {path}")
            
            # Check file size (limit to 10MB)
            file_size = os.path.getsize(path)
            if file_size > 10 * 1024 * 1024:
                raise ValueError(f"File too large: {file_size} bytes (max 10MB)")
            
            # Try to read as text
            try:
                async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                return content
            except UnicodeDecodeError:
                # If UTF-8 fails, try other encodings
                for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        async with aiofiles.open(path, 'r', encoding=encoding) as f:
                            content = await f.read()
                        return content
                    except UnicodeDecodeError:
                        continue
                raise ValueError(f"Cannot decode file {path} with any supported encoding")
                
        except Exception as e:
            raise Exception(f"Error reading file {path}: {str(e)}")
    
    async def write_file(self, path: str, content: str) -> None:
        """Write content to a file"""
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                await f.write(content)
            
            await self._format_file(path)
                
        except Exception as e:
            raise Exception(f"Error writing file {path}: {str(e)}")
    
    async def create_directory(self, path: str) -> None:
        """Create a new directory"""
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            raise Exception(f"Error creating directory {path}: {str(e)}")
    
    async def delete_file(self, path: str) -> None:
        """Delete a file or directory"""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path not found: {path}")
            
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
                
        except Exception as e:
            raise Exception(f"Error deleting {path}: {str(e)}")

    async def move_path(self, source_path: str, destination_path: str, overwrite: bool = False) -> None:
        """Move or rename a file/directory to a new location."""
        async def runner():
            src = self._resolve_path(source_path)
            dest = self._resolve_path(destination_path)

            if not os.path.exists(src):
                raise FileNotFoundError(f"Source path not found: {source_path}")

            # Prevent moving a directory into itself
            normalized_src = os.path.abspath(src)
            normalized_dest = os.path.abspath(dest)
            if normalized_dest.startswith(f"{normalized_src}{os.sep}"):
                raise ValueError("Destination cannot be inside the source directory")

            dest_dir = os.path.dirname(dest)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)

            if os.path.exists(dest):
                if not overwrite:
                    raise FileExistsError(f"Destination already exists: {destination_path}")
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                else:
                    os.remove(dest)

            shutil.move(src, dest)

        await asyncio.to_thread(runner)

    async def copy_path(self, source_path: str, destination_path: str, overwrite: bool = False) -> None:
        """Copy a file or directory to a destination path."""
        async def runner():
            src = self._resolve_path(source_path)
            dest = self._resolve_path(destination_path)

            if not os.path.exists(src):
                raise FileNotFoundError(f"Source path not found: {source_path}")

            dest_dir = dest if os.path.isdir(src) else os.path.dirname(dest)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)

            if os.path.exists(dest):
                if not overwrite:
                    raise FileExistsError(f"Destination already exists: {destination_path}")
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                else:
                    os.remove(dest)

            if os.path.isdir(src):
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)

        await asyncio.to_thread(runner)
    
    async def search_files(self, query: str, path: str = ".") -> List[Dict[str, Any]]:
        """Search for files by name"""
        try:
            results = []
            query_lower = query.lower()
            
            for root, dirs, files in os.walk(path):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if query_lower in file.lower():
                        file_path = os.path.join(root, file)
                        try:
                            file_info = FileInfo(file_path)
                            results.append({
                                "name": file_info.name,
                                "path": file_path,
                                "size": file_info.size,
                                "modified_time": file_info.modified_time,
                                "extension": file_info.extension
                            })
                        except (OSError, PermissionError):
                            continue
            
            return results[:50]  # Limit to 50 results
            
        except Exception as e:
            raise Exception(f"Error searching files: {str(e)}")

    async def _format_file(self, path: str) -> None:
        """Format files using language-specific formatters when available."""
        extension = os.path.splitext(path)[1].lower()
        formatter_cmd = None

        if extension == '.go':
            formatter_cmd = ['gofmt', '-w', path]
        elif extension == '.py':
            formatter_cmd = ['black', path]

        if not formatter_cmd:
            return

        try:
            process = await asyncio.create_subprocess_exec(
                *formatter_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                print(f"⚠️ Formatter {' '.join(formatter_cmd)} failed: {stderr.decode().strip()}")
        except FileNotFoundError:
            print(f"⚠️ Formatter not found for command: {' '.join(formatter_cmd)}")
        except Exception as e:
            print(f"⚠️ Failed to format {path}: {str(e)}")
    
    async def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get detailed information about a file or directory"""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path not found: {path}")
            
            file_info = FileInfo(path)
            return {
                "name": file_info.name,
                "path": file_info.path,
                "size": file_info.size,
                "is_directory": file_info.is_directory,
                "modified_time": file_info.modified_time,
                "extension": file_info.extension,
                "mime_type": mimetypes.guess_type(path)[0] if not file_info.is_directory else None,
                "is_code_file": file_info.extension in self.supported_extensions if file_info.extension else False
            }
            
        except Exception as e:
            raise Exception(f"Error getting file info: {str(e)}")
    
    async def get_project_structure(self, path: str = ".", max_depth: int = 6) -> Dict[str, Any]:
        """Return a hierarchical representation of the project files."""
        try:
            target_path = self._resolve_path(path)
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Path not found: {path}")

            depth = max(1, min(max_depth, 20))
            return self._build_tree(target_path, depth)

        except Exception as e:
            raise Exception(f"Error getting project structure: {str(e)}")

    def _build_tree(self, current_path: str, max_depth: int, current_depth: int = 0) -> Dict[str, Any]:
        is_directory = os.path.isdir(current_path)
        node = {
            "name": os.path.basename(current_path) or current_path,
            "path": self._normalize_path(current_path),
            "is_directory": is_directory,
            "children": [],
            "has_more_children": False
        }

        if is_directory:
            if current_depth >= max_depth:
                node["has_more_children"] = True
            else:
                children = []
                try:
                    entries = sorted(os.listdir(current_path))
                except (OSError, PermissionError):
                    entries = []

                for entry in entries:
                    if entry.startswith('.'):
                        continue
                    entry_path = os.path.join(current_path, entry)
                    children.append(self._build_tree(entry_path, max_depth, current_depth + 1))
                    if len(children) >= self.max_tree_children:
                        node["has_more_children"] = True
                        break

                node["children"] = children

        return node

    def _resolve_path(self, path: str) -> str:
        if not path:
            return self.current_directory
        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self.current_directory, path))

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.replace("\\", "/")
