from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os

router = APIRouter()


class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    is_directory: bool
    modified_time: str
    extension: Optional[str] = None


class FileContent(BaseModel):
    content: str
    path: str
    encoding: str = "utf-8"


class DirectoryListing(BaseModel):
    path: str
    files: List[FileInfo]
    total_files: int


class FileTreeNode(BaseModel):
    name: str
    path: str
    is_directory: bool
    has_more_children: bool = False
    children: List["FileTreeNode"] = Field(default_factory=list)


class FileTreeResponse(BaseModel):
    root_name: str
    root_path: str
    tree: FileTreeNode


class FileTransferRequest(BaseModel):
    source_path: str
    destination_path: str
    overwrite: bool = False


async def get_file_service(request: Request):
    """Dependency to get file service instance"""
    return request.app.state.file_service


@router.get("/list/{path:path}", response_model=DirectoryListing)
async def list_directory(
    path: str,
    file_service = Depends(get_file_service)
):
    """List files and directories in the specified path"""
    try:
        if not path or path == "/":
            path = "."
        
        files = await file_service.list_directory(path)
        return DirectoryListing(
            path=path,
            files=files,
            total_files=len(files)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing directory: {str(e)}")


@router.get("/read/{path:path}", response_model=FileContent)
async def read_file(
    path: str,
    file_service = Depends(get_file_service)
):
    """Read the content of a file"""
    try:
        content = await file_service.read_file(path)
        return FileContent(
            content=content,
            path=path,
            encoding="utf-8"
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail=f"Path is a directory, not a file: {path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")


@router.post("/write/{path:path}")
async def write_file(
    path: str,
    request_data: dict,
    file_service = Depends(get_file_service)
):
    """Write content to a file"""
    try:
        content = request_data.get("content", "")
        await file_service.write_file(path, content)
        return {"message": f"File {path} written successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")


@router.post("/create-directory/{path:path}")
async def create_directory(
    path: str,
    file_service = Depends(get_file_service)
):
    """Create a new directory"""
    try:
        await file_service.create_directory(path)
        return {"message": f"Directory {path} created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating directory: {str(e)}")


@router.delete("/delete/{path:path}")
async def delete_file(
    path: str,
    file_service = Depends(get_file_service)
):
    """Delete a file or directory"""
    try:
        await file_service.delete_file(path)
        return {"message": f"File/directory {path} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting file: {str(e)}")


@router.post("/move")
async def move_path(
    request_data: FileTransferRequest,
    file_service = Depends(get_file_service)
):
    """Move or rename a file/directory."""
    try:
        await file_service.move_path(
            request_data.source_path,
            request_data.destination_path,
            request_data.overwrite
        )
        return {"message": f"Moved {request_data.source_path} to {request_data.destination_path}"}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error moving path: {str(exc)}")


@router.post("/copy")
async def copy_path(
    request_data: FileTransferRequest,
    file_service = Depends(get_file_service)
):
    """Copy a file or directory."""
    try:
        await file_service.copy_path(
            request_data.source_path,
            request_data.destination_path,
            request_data.overwrite
        )
        return {"message": f"Copied {request_data.source_path} to {request_data.destination_path}"}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error copying path: {str(exc)}")


@router.get("/search/{query}")
async def search_files(
    query: str,
    path: str = ".",
    file_service = Depends(get_file_service)
):
    """Search for files by name"""
    try:
        results = await file_service.search_files(query, path)
        return {"results": results, "query": query, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching files: {str(e)}")


@router.get("/info/{path:path}", response_model=FileInfo)
async def get_file_info(
    path: str,
    file_service = Depends(get_file_service)
):
    """Get detailed information about a file or directory"""
    try:
        info = await file_service.get_file_info(path)
        return info
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting file info: {str(e)}")


@router.get("/tree/{path:path}", response_model=FileTreeResponse)
async def get_file_tree(
    path: str,
    max_depth: int = 6,
    file_service = Depends(get_file_service)
):
    """Return a hierarchical representation of the directory."""
    try:
        tree = await file_service.get_project_structure(path or ".", max_depth=max_depth)
        return {
            "root_name": tree["name"],
            "root_path": tree["path"],
            "tree": tree
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error building file tree: {str(e)}")


try:
    FileTreeNode.model_rebuild()  # Pydantic v2
except AttributeError:  # pragma: no cover - fallback for v1
    FileTreeNode.update_forward_refs()
