from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

router = APIRouter()


class CodeAnalysis(BaseModel):
    file_path: str
    language: str
    functions: List[Dict[str, Any]]
    classes: List[Dict[str, Any]]
    imports: List[str]
    complexity_score: float
    issues: List[Dict[str, Any]]


class CodeGenerationRequest(BaseModel):
    prompt: str
    language: str
    context: Optional[Dict[str, Any]] = None
    max_length: Optional[int] = 1000


class CodeGenerationResponse(BaseModel):
    generated_code: str
    explanation: str
    language: str
    confidence: float


class CodeSearchRequest(BaseModel):
    query: str
    path: str = "."
    language: Optional[str] = None
    max_results: int = 10


class CodeSearchResult(BaseModel):
    file_path: str
    line_number: int
    content: str
    context: str
    relevance_score: float


async def get_code_analyzer(request: Request):
    """Dependency to get code analyzer instance"""
    return request.app.state.code_analyzer

async def get_ai_service(request: Request):
    """Dependency to get AI service instance"""
    return request.app.state.ai_service


@router.post("/analyze/{path:path}", response_model=CodeAnalysis)
async def analyze_code(
    path: str,
    code_analyzer = Depends(get_code_analyzer)
):
    """Analyze a code file and extract information"""
    try:
        analysis = await code_analyzer.analyze_file(path)
        return analysis
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing code: {str(e)}")


@router.post("/generate", response_model=CodeGenerationResponse)
async def generate_code(
    request: CodeGenerationRequest,
    code_analyzer = Depends(get_code_analyzer),
    ai_service = Depends(get_ai_service)
):
    """Generate code based on a natural language prompt"""
    try:
        result = await code_analyzer.generate_code(
            prompt=request.prompt,
            language=request.language,
            context=request.context or {},
            max_length=request.max_length,
            ai_service=ai_service
        )
        return result
    except Exception as e:
        error_msg = str(e)
        # Check if it's a service unavailable error
        if "unavailable" in error_msg.lower() or "ollama" in error_msg.lower():
            raise HTTPException(status_code=503, detail=error_msg)
        raise HTTPException(status_code=500, detail=f"Error generating code: {error_msg}")


@router.post("/search", response_model=List[CodeSearchResult])
async def search_code(
    request: CodeSearchRequest,
    code_analyzer = Depends(get_code_analyzer)
):
    """Search for code patterns and functions"""
    try:
        results = await code_analyzer.search_code(
            query=request.query,
            path=request.path,
            language=request.language,
            max_results=request.max_results
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching code: {str(e)}")


@router.get("/languages")
async def get_supported_languages(code_analyzer = Depends(get_code_analyzer)):
    """Get list of supported programming languages"""
    try:
        languages = await code_analyzer.get_supported_languages()
        return {"languages": languages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting languages: {str(e)}")


@router.post("/refactor/{path:path}")
async def refactor_code(
    path: str,
    refactor_type: str,
    code_analyzer = Depends(get_code_analyzer)
):
    """Refactor code in a specific way"""
    try:
        result = await code_analyzer.refactor_code(path, refactor_type)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refactoring code: {str(e)}")


@router.get("/suggestions/{path:path}")
async def get_code_suggestions(
    path: str,
    line_number: int,
    code_analyzer = Depends(get_code_analyzer)
):
    """Get code suggestions for a specific line"""
    try:
        suggestions = await code_analyzer.get_suggestions(path, line_number)
        return {"suggestions": suggestions}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting suggestions: {str(e)}")
