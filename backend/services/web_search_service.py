"""
Enhanced Web Search Service
Provides improved web search capabilities with caching, better error handling, and result optimization
"""

import asyncio
import time
import hashlib
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict
import os

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS = None
    DDGS_AVAILABLE = False


class WebSearchService:
    """Enhanced web search service with caching and optimization"""
    
    def __init__(self, cache_size: int = 100, cache_ttl_seconds: int = 3600):
        """
        Initialize web search service
        
        Args:
            cache_size: Maximum number of cached search results
            cache_ttl_seconds: Time-to-live for cache entries in seconds (default: 1 hour)
        """
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl_seconds
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.search_history: List[Dict[str, Any]] = []
        self.max_history = 50
        
        # Rate limiting
        self.last_search_time = 0.0
        self.min_search_interval = 0.5  # Minimum seconds between searches
        
        # Search configuration
        self.default_max_results = 5
        self.max_results_limit = 20
        
        # Load cache from disk if available
        self._load_cache()
    
    def _get_cache_key(self, query: str, search_type: str = "text") -> str:
        """Generate cache key from query and search type"""
        key_string = f"{search_type}:{query.lower().strip()}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry is still valid"""
        if not cache_entry:
            return False
        
        cached_time = cache_entry.get("timestamp", 0)
        age = time.time() - cached_time
        return age < self.cache_ttl
    
    def _load_cache(self):
        """Load cache from disk if cache file exists"""
        cache_file = os.path.join(
            os.path.expanduser("~"),
            ".offline_ai_agent",
            "web_search_cache.json"
        )
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert list to OrderedDict
                    for key, value in data.get("cache", {}).items():
                        if self._is_cache_valid(value):
                            self.cache[key] = value
        except Exception:
            pass  # If cache loading fails, start with empty cache
    
    def _save_cache(self):
        """Save cache to disk"""
        cache_file = os.path.join(
            os.path.expanduser("~"),
            ".offline_ai_agent",
            "web_search_cache.json"
        )
        
        try:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            # Convert OrderedDict to regular dict for JSON serialization
            cache_data = {k: v for k, v in self.cache.items()}
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({"cache": cache_data}, f, indent=2)
        except Exception:
            pass  # If cache saving fails, continue without persistence
    
    def _optimize_query(self, query: str) -> str:
        """Optimize search query for better results"""
        query_lower = query.lower()
        
        # For price queries, add "current" or "live" if not present
        is_price_query = any(keyword in query_lower for keyword in [
            "price", "cost", "value", "worth", "rate", "bitcoin", "btc", "ethereum", "eth",
            "crypto", "stock", "currency", "exchange rate"
        ])
        
        if is_price_query:
            # Add "current" if not already present
            if "current" not in query_lower and "live" not in query_lower and "today" not in query_lower and "now" not in query_lower:
                return f"current {query}".strip()
            return query.strip()
        
        # Remove common stop words that don't help search
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        
        # Split and filter
        words = query.split()
        optimized = [w for w in words if w.lower() not in stop_words or len(words) <= 3]
        
        # Rejoin
        optimized_query = " ".join(optimized)
        
        # If optimization removed too much, use original
        if len(optimized_query.strip()) < len(query.strip()) * 0.5:
            return query.strip()
        
        return optimized_query.strip()
    
    def _rate_limit(self):
        """Implement rate limiting between searches"""
        current_time = time.time()
        time_since_last = current_time - self.last_search_time
        
        if time_since_last < self.min_search_interval:
            sleep_time = self.min_search_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_search_time = time.time()
    
    def _score_relevance(self, result: Dict[str, Any], query: str) -> float:
        """Score search result relevance based on query"""
        score = 0.0
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        # Check title
        title = (result.get("title") or "").lower()
        if title:
            title_words = set(title.split())
            common_words = query_words.intersection(title_words)
            score += len(common_words) * 2.0  # Title matches are more important
        
        # Check snippet/body
        body = (result.get("body") or result.get("description") or "").lower()
        if body:
            body_words = set(body.split())
            common_words = query_words.intersection(body_words)
            score += len(common_words) * 1.0
        
        # Boost for exact phrase matches
        if query_lower in title:
            score += 3.0
        if query_lower in body:
            score += 2.0
        
        # Boost for domain authority (simple heuristic)
        url = result.get("href") or result.get("url") or ""
        if any(domain in url.lower() for domain in ["github.com", "stackoverflow.com", "docs.python.org", "developer.mozilla.org"]):
            score += 1.5
        
        return score
    
    def _format_result(self, result: Dict[str, Any], index: int, query: str) -> str:
        """Format a single search result for display"""
        title = result.get("title", "No title")
        url = result.get("href") or result.get("url", "N/A")
        body = result.get("body") or result.get("description", "No description")
        
        # Truncate long descriptions
        max_body_length = 300
        if len(body) > max_body_length:
            body = body[:max_body_length].rsplit(' ', 1)[0] + "..."
        
        # Extract domain from URL
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
        except Exception:
            domain = url[:50] if len(url) > 50 else url
        
        formatted = f"{index}. {title}"
        formatted += f"\n   Source: {domain}"
        formatted += f"\n   URL: {url}"
        formatted += f"\n   {body}"
        
        return formatted
    
    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        search_type: str = "text",
        use_cache: bool = True,
        optimize_query: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Perform web search with enhanced features
        
        Args:
            query: Search query
            max_results: Maximum number of results (default: 5, max: 20)
            search_type: Type of search ("text", "news", "images")
            use_cache: Whether to use cached results if available
            optimize_query: Whether to optimize the query
        
        Returns:
            Tuple of (results, metadata)
        """
        if not DDGS_AVAILABLE:
            return [], {"error": "DuckDuckGo search not available. Install duckduckgo-search package."}
        
        if not query or not query.strip():
            return [], {"error": "Empty search query"}
        
        # Optimize query if requested
        original_query = query
        if optimize_query:
            query = self._optimize_query(query)
        
        # Limit max results
        max_results = min(max_results or self.default_max_results, self.max_results_limit)
        
        # Check cache
        cache_key = self._get_cache_key(query, search_type)
        if use_cache and cache_key in self.cache:
            cached_entry = self.cache[cache_key]
            if self._is_cache_valid(cached_entry):
                # Move to end (most recently used)
                self.cache.move_to_end(cache_key)
                metadata = cached_entry.get("metadata", {})
                metadata["cached"] = True
                metadata["cache_age_seconds"] = int(time.time() - cached_entry.get("timestamp", 0))
                return cached_entry.get("results", []), metadata
        
        # Rate limiting
        self._rate_limit()
        
        # Perform search
        try:
            loop = asyncio.get_event_loop()
            
            def perform_search():
                results = []
                with DDGS() as ddgs:
                    if search_type == "news":
                        search_method = ddgs.news
                    elif search_type == "images":
                        search_method = ddgs.images
                    else:
                        search_method = ddgs.text
                    
                    for result in search_method(query, max_results=max_results):
                        results.append(dict(result))
                
                return results
            
            # Run search in executor to avoid blocking
            results = await loop.run_in_executor(None, perform_search)
            
            # Score and sort by relevance
            scored_results = []
            for result in results:
                score = self._score_relevance(result, original_query)
                scored_results.append((score, result))
            
            # Sort by score (descending)
            scored_results.sort(key=lambda x: x[0], reverse=True)
            results = [result for _, result in scored_results]
            
            # Store in cache
            cache_entry = {
                "results": results,
                "timestamp": time.time(),
                "query": original_query,
                "optimized_query": query,
                "metadata": {
                    "result_count": len(results),
                    "search_type": search_type,
                    "cached": False
                }
            }
            
            # Add to cache (with size limit)
            self.cache[cache_key] = cache_entry
            if len(self.cache) > self.cache_size:
                # Remove oldest entry
                self.cache.popitem(last=False)
            
            # Move to end (most recently used)
            self.cache.move_to_end(cache_key)
            
            # Save cache to disk
            self._save_cache()
            
            # Record in history
            self.search_history.append({
                "query": original_query,
                "optimized_query": query,
                "result_count": len(results),
                "timestamp": datetime.now().isoformat(),
                "search_type": search_type
            })
            if len(self.search_history) > self.max_history:
                self.search_history.pop(0)
            
            metadata = cache_entry["metadata"]
            return results, metadata
            
        except Exception as e:
            error_msg = str(e)
            return [], {
                "error": error_msg,
                "error_type": type(e).__name__
            }
    
    def format_results(
        self,
        results: List[Dict[str, Any]],
        query: str,
        include_metadata: bool = False
    ) -> str:
        """Format search results as a readable string"""
        if not results:
            return "No search results found."
        
        lines = [f"Web search results for '{query}':"]
        lines.append(f"Found {len(results)} result(s)\n")
        
        for idx, result in enumerate(results, 1):
            lines.append(self._format_result(result, idx, query))
            lines.append("")
        
        if include_metadata:
            lines.append("\n---")
            lines.append("Tip: Use these results to inform your response.")
        
        return "\n".join(lines)
    
    def get_search_suggestions(self, partial_query: str) -> List[str]:
        """Get search suggestions based on partial query (placeholder for future enhancement)"""
        # This could be enhanced with actual autocomplete API
        # For now, return empty list
        return []
    
    def clear_cache(self):
        """Clear the search cache"""
        self.cache.clear()
        self._save_cache()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        valid_entries = sum(1 for entry in self.cache.values() if self._is_cache_valid(entry))
        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "cache_size_limit": self.cache_size,
            "cache_ttl_seconds": self.cache_ttl
        }
    
    def get_search_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent search history"""
        return self.search_history[-limit:]

