"""
Web Search API endpoints
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from backend.services.web_search_service import WebSearchService
import os

router = APIRouter()


class WebSearchRequest(BaseModel):
    """Request model for web search"""
    query: str = Field(..., description="Search query")
    max_results: Optional[int] = Field(5, ge=1, le=20, description="Maximum number of results")
    search_type: Optional[str] = Field("text", description="Type of search: text, news, or images")
    use_cache: Optional[bool] = Field(True, description="Whether to use cached results")
    optimize_query: Optional[bool] = Field(True, description="Whether to optimize the query")
    deduplicate: Optional[bool] = Field(True, description="Whether to remove duplicate results")
    filter_domains: Optional[List[str]] = Field(None, description="List of domains to include (whitelist)")
    exclude_domains: Optional[List[str]] = Field(None, description="List of domains to exclude (blacklist)")


class MultiSearchRequest(BaseModel):
    """Request model for multiple queries"""
    queries: List[str] = Field(..., min_items=1, description="List of search queries")
    max_results_per_query: Optional[int] = Field(5, ge=1, le=20, description="Max results per query")
    search_type: Optional[str] = Field("text", description="Type of search")
    combine_results: Optional[bool] = Field(True, description="Whether to combine and deduplicate results")


class WebSearchResponse(BaseModel):
    """Response model for web search"""
    results: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    query: str
    result_count: int


class SearchSummaryRequest(BaseModel):
    """Request model for search result summarization"""
    results: List[Dict[str, Any]] = Field(..., description="Search results to summarize")
    max_length: Optional[int] = Field(500, description="Maximum length of summary")


# Global web search service instance
_web_search_service: Optional[WebSearchService] = None


def get_web_search_service() -> WebSearchService:
    """Get or create web search service instance"""
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService(
            cache_size=int(os.getenv("WEB_SEARCH_CACHE_SIZE", "100")),
            cache_ttl_seconds=int(os.getenv("WEB_SEARCH_CACHE_TTL", "3600"))
        )
    return _web_search_service


@router.post("/search", response_model=WebSearchResponse)
async def search_web(
    request: WebSearchRequest,
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Perform web search with enhanced features
    
    Features:
    - Query optimization
    - Result deduplication
    - Relevance scoring
    - Caching
    - Domain filtering
    - Retry logic with exponential backoff
    """
    try:
        results, metadata = await web_search_service.search(
            query=request.query,
            max_results=request.max_results,
            search_type=request.search_type,
            use_cache=request.use_cache,
            optimize_query=request.optimize_query,
            deduplicate=request.deduplicate,
            filter_domains=request.filter_domains,
            exclude_domains=request.exclude_domains
        )
        
        if "error" in metadata:
            raise HTTPException(status_code=500, detail=metadata["error"])
        
        return WebSearchResponse(
            results=results,
            metadata=metadata,
            query=request.query,
            result_count=len(results)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error performing web search: {str(e)}")


@router.post("/search/multiple", response_model=WebSearchResponse)
async def search_multiple_queries(
    request: MultiSearchRequest,
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Search multiple queries and optionally combine results
    
    Useful for:
    - Related searches
    - Query expansion
    - Comprehensive research
    """
    try:
        results, metadata = await web_search_service.search_multiple(
            queries=request.queries,
            max_results_per_query=request.max_results_per_query,
            search_type=request.search_type,
            combine_results=request.combine_results
        )
        
        if "error" in metadata:
            raise HTTPException(status_code=500, detail=metadata["error"])
        
        return WebSearchResponse(
            results=results,
            metadata=metadata,
            query=", ".join(request.queries),
            result_count=len(results)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error performing multi-query search: {str(e)}")


@router.post("/search/summarize")
async def summarize_search_results(
    request: SearchSummaryRequest,
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Create a summary of search results
    """
    try:
        summary = web_search_service.summarize_results(
            results=request.results,
            max_length=request.max_length
        )
        return {
            "summary": summary,
            "result_count": len(request.results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error summarizing results: {str(e)}")


@router.get("/search/history")
async def get_search_history(
    limit: int = 10,
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Get recent search history
    """
    try:
        history = web_search_service.get_search_history(limit=limit)
        return {
            "history": history,
            "count": len(history)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving search history: {str(e)}")


@router.get("/search/cache/stats")
async def get_cache_stats(
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Get cache statistics
    """
    try:
        stats = web_search_service.get_cache_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving cache stats: {str(e)}")


@router.delete("/search/cache")
async def clear_cache(
    web_search_service: WebSearchService = Depends(get_web_search_service)
):
    """
    Clear the search cache
    """
    try:
        web_search_service.clear_cache()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")

