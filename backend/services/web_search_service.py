"""
Enhanced Web Search Service
Provides improved web search capabilities with caching, better error handling, and result optimization
"""

import asyncio
import time
import hashlib
import json
import re
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timedelta
from collections import OrderedDict
from urllib.parse import urlparse, urlunparse
import os
import logging

logger = logging.getLogger(__name__)

try:
    from ddgs import DDGS  # type: ignore
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore
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
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay_base = 1.0  # Base delay in seconds
        self.retry_delay_max = 10.0  # Maximum delay in seconds
        
        # Query expansion synonyms (basic dictionary)
        self.query_synonyms = {
            "how to": ["tutorial", "guide", "learn"],
            "install": ["setup", "configure", "deploy"],
            "error": ["issue", "problem", "bug", "fix"],
            "best": ["top", "recommended", "popular"],
            "compare": ["vs", "versus", "difference"],
            "price": ["cost", "pricing", "fee"],
            "free": ["gratis", "no cost", "open source"],
        }
        
        # Trusted domains for relevance boosting
        self.trusted_domains = {
            "github.com", "stackoverflow.com", "docs.python.org", 
            "developer.mozilla.org", "w3.org", "python.org",
            "npmjs.com", "pypi.org", "rust-lang.org", "go.dev",
            "nodejs.org", "react.dev", "vuejs.org", "angular.io"
        }
        
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
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication"""
        try:
            parsed = urlparse(url)
            # Remove fragment, normalize scheme and netloc
            normalized = urlunparse((
                parsed.scheme.lower() if parsed.scheme else '',
                parsed.netloc.lower() if parsed.netloc else '',
                parsed.path.rstrip('/') if parsed.path else '',
                parsed.params,
                parsed.query,
                ''  # Remove fragment
            ))
            return normalized
        except Exception:
            return url.lower().strip()
    
    def _expand_query(self, query: str) -> List[str]:
        """Expand query with synonyms and variations"""
        expansions = [query]  # Always include original
        query_lower = query.lower()
        words = query_lower.split()
        
        # Try to expand individual words
        for word in words:
            if word in self.query_synonyms:
                for synonym in self.query_synonyms[word]:
                    expanded = query_lower.replace(word, synonym)
                    if expanded != query_lower:
                        expansions.append(expanded)
        
        # Limit expansions to avoid too many queries
        return expansions[:3]  # Original + up to 2 expansions
    
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
    
    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate results based on URL and similar content"""
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        deduplicated = []
        
        for result in results:
            url = result.get("href") or result.get("url") or ""
            title = (result.get("title") or "").lower().strip()
            
            # Normalize URL
            normalized_url = self._normalize_url(url)
            
            # Skip if we've seen this URL before
            if normalized_url in seen_urls:
                continue
            
            # Skip if title is very similar (fuzzy match)
            title_key = title[:50]  # Use first 50 chars as key
            if title_key in seen_titles and len(title_key) > 10:
                # Check if titles are very similar
                similarity = self._calculate_similarity(title, list(seen_titles)[0])
                if similarity > 0.9:  # 90% similar
                    continue
            
            seen_urls.add(normalized_url)
            if title_key:
                seen_titles.add(title_key)
            deduplicated.append(result)
        
        return deduplicated
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate simple similarity between two strings"""
        if not str1 or not str2:
            return 0.0
        
        # Simple word overlap similarity
        words1 = set(str1.lower().split())
        words2 = set(str2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    def _rate_limit(self):
        """Implement rate limiting between searches"""
        current_time = time.time()
        time_since_last = current_time - self.last_search_time
        
        if time_since_last < self.min_search_interval:
            sleep_time = self.min_search_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_search_time = time.time()
    
    def _score_relevance(self, result: Dict[str, Any], query: str) -> float:
        """Score search result relevance based on query with improved algorithm"""
        score = 0.0
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        # Check title
        title = (result.get("title") or "").lower()
        if title:
            title_words = set(title.split())
            common_words = query_words.intersection(title_words)
            score += len(common_words) * 2.5  # Title matches are more important
            
            # Boost for query words at the start of title
            title_start = " ".join(title.split()[:3])
            if any(word in title_start for word in query_words):
                score += 1.0
        
        # Check snippet/body
        body = (result.get("body") or result.get("description") or "").lower()
        if body:
            body_words = set(body.split())
            common_words = query_words.intersection(body_words)
            score += len(common_words) * 1.0
            
            # Boost for multiple occurrences
            for word in query_words:
                count = body.count(word)
                if count > 1:
                    score += 0.2 * (count - 1)  # Diminishing returns
        
        # Boost for exact phrase matches
        if query_lower in title:
            score += 4.0
        if query_lower in body:
            score += 2.5
        
        # Boost for partial phrase matches (consecutive words)
        query_phrases = self._extract_phrases(query_lower)
        for phrase in query_phrases:
            if len(phrase.split()) >= 2:
                if phrase in title:
                    score += 2.0
                if phrase in body:
                    score += 1.0
        
        # Boost for domain authority
        url = result.get("href") or result.get("url") or ""
        try:
            domain = urlparse(url).netloc.lower()
            if domain in self.trusted_domains:
                score += 2.0  # Increased boost for trusted domains
            elif any(trusted in domain for trusted in self.trusted_domains):
                score += 1.0
        except Exception:
            pass
        
        # Penalize very short titles or bodies (likely low quality)
        if title and len(title) < 10:
            score -= 0.5
        if body and len(body) < 20:
            score -= 0.3
        
        # Boost for recent content (if date available)
        date = result.get("date") or result.get("published")
        if date:
            try:
                # Try to parse date and boost recent content
                if isinstance(date, str):
                    # Simple heuristic: if date string contains current year
                    current_year = str(datetime.now().year)
                    if current_year in date:
                        score += 0.5
            except Exception:
                pass
        
        return max(0.0, score)  # Ensure non-negative
    
    def _extract_phrases(self, text: str, min_words: int = 2, max_words: int = 4) -> List[str]:
        """Extract phrases (consecutive word sequences) from text"""
        words = text.split()
        phrases = []
        for i in range(len(words)):
            for j in range(i + min_words, min(i + max_words + 1, len(words) + 1)):
                phrase = " ".join(words[i:j])
                phrases.append(phrase)
        return phrases
    
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
    
    async def _perform_search_with_retry(
        self,
        query: str,
        max_results: int,
        search_type: str
    ) -> List[Dict[str, Any]]:
        """Perform search with retry logic and exponential backoff"""
        last_exception = None
        
        for attempt in range(self.max_retries):
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
                        
                        for result in search_method(query, max_results=max_results * 2):  # Get more for deduplication
                            results.append(dict(result))
                    
                    return results
                
                # Run search in executor to avoid blocking
                results = await loop.run_in_executor(None, perform_search)
                return results
                
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    # Calculate exponential backoff delay
                    delay = min(
                        self.retry_delay_base * (2 ** attempt),
                        self.retry_delay_max
                    )
                    logger.warning(f"Search attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries} search attempts failed. Last error: {e}")
        
        # If all retries failed, raise the last exception
        raise last_exception or Exception("Search failed after retries")
    
    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        search_type: str = "text",
        use_cache: bool = True,
        optimize_query: bool = True,
        deduplicate: bool = True,
        filter_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Perform web search with enhanced features
        
        Args:
            query: Search query
            max_results: Maximum number of results (default: 5, max: 20)
            search_type: Type of search ("text", "news", "images")
            use_cache: Whether to use cached results if available
            optimize_query: Whether to optimize the query
            deduplicate: Whether to remove duplicate results
            filter_domains: Optional list of domains to include (whitelist)
            exclude_domains: Optional list of domains to exclude (blacklist)
        
        Returns:
            Tuple of (results, metadata)
        """
        if not DDGS_AVAILABLE:
            return [], {"error": "DuckDuckGo search not available. Install the 'ddgs' package."}
        
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
                results = cached_entry.get("results", [])
                
                # Apply filters even to cached results
                results = self._filter_results(results, filter_domains, exclude_domains)
                if deduplicate:
                    results = self._deduplicate_results(results)
                
                return results[:max_results], metadata
        
        # Rate limiting
        self._rate_limit()
        
        # Perform search with retry
        try:
            results = await self._perform_search_with_retry(query, max_results, search_type)
            
            # Apply domain filters
            results = self._filter_results(results, filter_domains, exclude_domains)
            
            # Deduplicate results
            if deduplicate:
                results = self._deduplicate_results(results)
            
            # Score and sort by relevance
            scored_results = []
            for result in results:
                score = self._score_relevance(result, original_query)
                scored_results.append((score, result))
            
            # Sort by score (descending)
            scored_results.sort(key=lambda x: x[0], reverse=True)
            results = [result for _, result in scored_results]
            
            # Limit to max_results
            results = results[:max_results]
            
            # Store in cache
            cache_entry = {
                "results": results,
                "timestamp": time.time(),
                "query": original_query,
                "optimized_query": query,
                "metadata": {
                    "result_count": len(results),
                    "search_type": search_type,
                    "cached": False,
                    "deduplicated": deduplicate
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
            logger.error(f"Web search failed: {error_msg}")
            return [], {
                "error": error_msg,
                "error_type": type(e).__name__
            }
    
    def _filter_results(
        self,
        results: List[Dict[str, Any]],
        filter_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Filter results by domain whitelist/blacklist"""
        if not filter_domains and not exclude_domains:
            return results
        
        filtered = []
        for result in results:
            url = result.get("href") or result.get("url") or ""
            try:
                domain = urlparse(url).netloc.lower()
                
                # Check blacklist
                if exclude_domains:
                    if any(excluded in domain for excluded in exclude_domains):
                        continue
                
                # Check whitelist
                if filter_domains:
                    if not any(allowed in domain for allowed in filter_domains):
                        continue
                
                filtered.append(result)
            except Exception:
                # If URL parsing fails, include the result
                filtered.append(result)
        
        return filtered
    
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
    
    async def search_multiple(
        self,
        queries: List[str],
        max_results_per_query: Optional[int] = None,
        search_type: str = "text",
        combine_results: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Search multiple queries and optionally combine results
        
        Args:
            queries: List of search queries
            max_results_per_query: Max results per query
            search_type: Type of search
            combine_results: If True, combine and deduplicate all results
        
        Returns:
            Tuple of (results, metadata)
        """
        if not queries:
            return [], {"error": "No queries provided"}
        
        all_results = []
        metadata_list = []
        
        for query in queries:
            results, metadata = await self.search(
                query=query,
                max_results=max_results_per_query,
                search_type=search_type,
                use_cache=True,
                optimize_query=True,
                deduplicate=False  # Deduplicate at the end if combining
            )
            all_results.extend(results)
            metadata_list.append(metadata)
        
        if combine_results:
            # Deduplicate across all queries
            all_results = self._deduplicate_results(all_results)
            
            # Re-score and sort all results
            scored_results = []
            # Use first query for scoring (or combine all queries)
            combined_query = " ".join(queries[:3])  # Use first 3 queries
            for result in all_results:
                score = self._score_relevance(result, combined_query)
                scored_results.append((score, result))
            
            scored_results.sort(key=lambda x: x[0], reverse=True)
            all_results = [result for _, result in scored_results]
        
        combined_metadata = {
            "query_count": len(queries),
            "total_results": len(all_results),
            "queries": queries,
            "combined": combine_results,
            "individual_metadata": metadata_list
        }
        
        return all_results, combined_metadata
    
    def summarize_results(
        self,
        results: List[Dict[str, Any]],
        max_length: int = 500
    ) -> str:
        """
        Create a summary of search results
        
        Args:
            results: List of search results
            max_length: Maximum length of summary
        
        Returns:
            Summary string
        """
        if not results:
            return "No results to summarize."
        
        summary_parts = []
        summary_parts.append(f"Found {len(results)} search result(s):\n")
        
        for idx, result in enumerate(results[:5], 1):  # Summarize top 5
            title = result.get("title", "No title")
            snippet = result.get("body") or result.get("description", "")
            
            # Truncate snippet
            if len(snippet) > 150:
                snippet = snippet[:150].rsplit(' ', 1)[0] + "..."
            
            summary_parts.append(f"{idx}. {title}")
            if snippet:
                summary_parts.append(f"   {snippet}")
            summary_parts.append("")
        
        if len(results) > 5:
            summary_parts.append(f"... and {len(results) - 5} more result(s)")
        
        summary = "\n".join(summary_parts)
        
        # Truncate if too long
        if len(summary) > max_length:
            summary = summary[:max_length].rsplit('\n', 1)[0] + "\n... (truncated)"
        
        return summary

