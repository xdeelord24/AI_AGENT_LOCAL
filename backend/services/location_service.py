"""
Location Service for AI Agent
Provides location detection, weather, and news services

Features:
- IP-based geolocation detection
- Weather API integration (OpenWeatherMap or similar)
- News API integration for location-based news
"""

import asyncio
import logging
import os
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import aiohttp
import json

logger = logging.getLogger(__name__)


class LocationService:
    """
    Location Service - Provides location detection, weather, and news
    
    This service enables the AI to:
    - Detect user location via IP geolocation
    - Get current weather for any location
    - Get location-based news
    """
    
    def __init__(self):
        """Initialize location service with API keys from environment"""
        # API keys from environment variables
        self.weather_api_key = os.getenv("OPENWEATHER_API_KEY", "")
        self.news_api_key = os.getenv("NEWS_API_KEY", "")
        
        # Cache for location, weather, and news
        self._location_cache: Dict[str, Dict[str, Any]] = {}
        self._weather_cache: Dict[str, Dict[str, Any]] = {}
        self._news_cache: Dict[str, Dict[str, Any]] = {}
        
        # Cache TTLs
        self.location_cache_ttl = 3600  # 1 hour for location
        self.weather_cache_ttl = 600  # 10 minutes for weather
        self.news_cache_ttl = 1800  # 30 minutes for news
        
        # Rate limiting
        self.last_api_call = {}
        self.min_api_interval = 1.0  # Minimum seconds between API calls
        
    async def get_user_location(self, ip_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Get user location based on IP address
        
        Uses free IP geolocation APIs:
        1. ipapi.co (primary)
        2. ip-api.com (fallback)
        
        Args:
            ip_address: Optional IP address. If None, uses public IP detection
            
        Returns:
            Dictionary with location information:
            {
                "city": str,
                "region": str,
                "country": str,
                "country_code": str,
                "latitude": float,
                "longitude": float,
                "timezone": str,
                "ip": str
            }
        """
        cache_key = ip_address or "current"
        
        # Check cache
        if cache_key in self._location_cache:
            cached = self._location_cache[cache_key]
            if time.time() - cached.get("timestamp", 0) < self.location_cache_ttl:
                logger.info(f"Returning cached location for {cache_key}")
                return cached.get("data", {})
        
        try:
            # Try ipapi.co first (free tier: 1000 requests/day)
            location = await self._get_location_ipapi(ip_address)
            if location:
                self._location_cache[cache_key] = {
                    "data": location,
                    "timestamp": time.time()
                }
                return location
            
            # Fallback to ip-api.com (free tier: 45 requests/minute)
            location = await self._get_location_ipapi_com(ip_address)
            if location:
                self._location_cache[cache_key] = {
                    "data": location,
                    "timestamp": time.time()
                }
                return location
                
            return {
                "error": "Unable to determine location",
                "city": "Unknown",
                "country": "Unknown"
            }
        except Exception as e:
            logger.error(f"Error getting location: {e}", exc_info=True)
            return {
                "error": str(e),
                "city": "Unknown",
                "country": "Unknown"
            }
    
    async def _get_location_ipapi(self, ip_address: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get location using ipapi.co"""
        try:
            url = "https://ipapi.co/json/"
            if ip_address:
                url = f"https://ipapi.co/{ip_address}/json/"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" not in data:
                            return {
                                "city": data.get("city", "Unknown"),
                                "region": data.get("region", "Unknown"),
                                "country": data.get("country_name", "Unknown"),
                                "country_code": data.get("country_code", ""),
                                "latitude": data.get("latitude", 0.0),
                                "longitude": data.get("longitude", 0.0),
                                "timezone": data.get("timezone", ""),
                                "ip": data.get("ip", ip_address or "Unknown")
                            }
        except Exception as e:
            logger.debug(f"ipapi.co failed: {e}")
        return None
    
    async def _get_location_ipapi_com(self, ip_address: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get location using ip-api.com"""
        try:
            url = "http://ip-api.com/json/"
            if ip_address:
                url = f"http://ip-api.com/json/{ip_address}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "success":
                            return {
                                "city": data.get("city", "Unknown"),
                                "region": data.get("regionName", "Unknown"),
                                "country": data.get("country", "Unknown"),
                                "country_code": data.get("countryCode", ""),
                                "latitude": data.get("lat", 0.0),
                                "longitude": data.get("lon", 0.0),
                                "timezone": data.get("timezone", ""),
                                "ip": data.get("query", ip_address or "Unknown")
                            }
        except Exception as e:
            logger.debug(f"ip-api.com failed: {e}")
        return None
    
    async def get_weather(
        self, 
        city: Optional[str] = None, 
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        units: str = "metric"
    ) -> Dict[str, Any]:
        """
        Get current weather for a location
        
        Args:
            city: City name (e.g., "London")
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            units: Temperature units ("metric" for Celsius, "imperial" for Fahrenheit)
            
        Returns:
            Dictionary with weather information
        """
        # Determine cache key
        if city:
            cache_key = f"city:{city.lower()}"
        elif latitude and longitude:
            cache_key = f"coord:{latitude:.2f},{longitude:.2f}"
        else:
            return {"error": "Either city or coordinates must be provided"}
        
        # Check cache
        if cache_key in self._weather_cache:
            cached = self._weather_cache[cache_key]
            if time.time() - cached.get("timestamp", 0) < self.weather_cache_ttl:
                logger.info(f"Returning cached weather for {cache_key}")
                return cached.get("data", {})
        
        # Use OpenWeatherMap if API key is available
        if self.weather_api_key:
            weather = await self._get_weather_openweathermap(city, latitude, longitude, units)
            if weather and "error" not in weather:
                self._weather_cache[cache_key] = {
                    "data": weather,
                    "timestamp": time.time()
                }
                return weather
        
        # Fallback to wttr.in (free, no API key required)
        weather = await self._get_weather_wttr(city, latitude, longitude, units)
        if weather:
            self._weather_cache[cache_key] = {
                "data": weather,
                "timestamp": time.time()
            }
            return weather
        
        return {"error": "Unable to fetch weather data"}
    
    async def _get_weather_openweathermap(
        self,
        city: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        units: str
    ) -> Optional[Dict[str, Any]]:
        """Get weather using OpenWeatherMap API"""
        try:
            if city:
                url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={self.weather_api_key}&units={units}"
            elif latitude and longitude:
                url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={self.weather_api_key}&units={units}"
            else:
                return None
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "location": data.get("name", city or "Unknown"),
                            "country": data.get("sys", {}).get("country", ""),
                            "temperature": data.get("main", {}).get("temp", 0),
                            "feels_like": data.get("main", {}).get("feels_like", 0),
                            "description": data.get("weather", [{}])[0].get("description", ""),
                            "humidity": data.get("main", {}).get("humidity", 0),
                            "wind_speed": data.get("wind", {}).get("speed", 0),
                            "pressure": data.get("main", {}).get("pressure", 0),
                            "visibility": data.get("visibility", 0),
                            "units": units,
                            "source": "OpenWeatherMap"
                        }
        except Exception as e:
            logger.debug(f"OpenWeatherMap API failed: {e}")
        return None
    
    async def _get_weather_wttr(
        self,
        city: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        units: str
    ) -> Optional[Dict[str, Any]]:
        """Get weather using wttr.in (free, no API key)"""
        try:
            if city:
                location_param = city.replace(" ", "+")
            elif latitude and longitude:
                location_param = f"{latitude},{longitude}"
            else:
                return None
            
            # wttr.in format: ?format=j1 for JSON
            url = f"https://wttr.in/{location_param}?format=j1"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        current = data.get("current_condition", [{}])[0]
                        nearest_area = data.get("nearest_area", [{}])[0]
                        
                        temp_c = float(current.get("temp_C", 0))
                        temp_f = float(current.get("temp_F", 0))
                        
                        return {
                            "location": nearest_area.get("areaName", [{}])[0].get("value", city or "Unknown"),
                            "country": nearest_area.get("country", [{}])[0].get("value", ""),
                            "temperature": temp_f if units == "imperial" else temp_c,
                            "feels_like": temp_c,  # wttr.in doesn't provide feels_like
                            "description": current.get("weatherDesc", [{}])[0].get("value", ""),
                            "humidity": int(current.get("humidity", 0)),
                            "wind_speed": float(current.get("windspeedKmph", 0)),
                            "pressure": int(current.get("pressure", 0)),
                            "visibility": float(current.get("visibility", 0)),
                            "units": units,
                            "source": "wttr.in"
                        }
        except Exception as e:
            logger.debug(f"wttr.in API failed: {e}")
        return None
    
    async def get_news(
        self,
        city: Optional[str] = None,
        country: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Get news for a location
        
        Args:
            city: City name
            country: Country name or code
            query: Optional search query
            max_results: Maximum number of results (default: 10)
            
        Returns:
            Dictionary with news articles
        """
        # Build cache key
        cache_key_parts = []
        if city:
            cache_key_parts.append(f"city:{city.lower()}")
        if country:
            cache_key_parts.append(f"country:{country.lower()}")
        if query:
            cache_key_parts.append(f"query:{query.lower()}")
        cache_key = "|".join(cache_key_parts) if cache_key_parts else "general"
        
        # Check cache
        if cache_key in self._news_cache:
            cached = self._news_cache[cache_key]
            if time.time() - cached.get("timestamp", 0) < self.news_cache_ttl:
                logger.info(f"Returning cached news for {cache_key}")
                return cached.get("data", {})
        
        # Build search query
        search_query_parts = []
        if city:
            search_query_parts.append(city)
        if country:
            search_query_parts.append(country)
        if query:
            search_query_parts.append(query)
        
        search_query = " ".join(search_query_parts) if search_query_parts else "news"
        
        # Use NewsAPI if API key is available
        if self.news_api_key:
            news = await self._get_news_newsapi(search_query, country, max_results)
            if news and "error" not in news:
                self._news_cache[cache_key] = {
                    "data": news,
                    "timestamp": time.time()
                }
                return news
        
        # Fallback to web search for news
        news = await self._get_news_web_search(search_query, max_results)
        if news:
            self._news_cache[cache_key] = {
                "data": news,
                "timestamp": time.time()
            }
            return news
        
        return {"error": "Unable to fetch news data", "articles": []}
    
    async def _get_news_newsapi(
        self,
        query: str,
        country: Optional[str],
        max_results: int
    ) -> Optional[Dict[str, Any]]:
        """Get news using NewsAPI"""
        try:
            # Build URL
            if country:
                url = f"https://newsapi.org/v2/top-headlines?country={country}&apiKey={self.news_api_key}"
            else:
                url = f"https://newsapi.org/v2/everything?q={query}&apiKey={self.news_api_key}&sortBy=publishedAt&pageSize={max_results}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        articles = data.get("articles", [])
                        return {
                            "query": query,
                            "total_results": data.get("totalResults", len(articles)),
                            "articles": [
                                {
                                    "title": article.get("title", ""),
                                    "description": article.get("description", ""),
                                    "url": article.get("url", ""),
                                    "source": article.get("source", {}).get("name", ""),
                                    "published_at": article.get("publishedAt", "")
                                }
                                for article in articles[:max_results]
                            ],
                            "source": "NewsAPI"
                        }
        except Exception as e:
            logger.debug(f"NewsAPI failed: {e}")
        return None
    
    async def _get_news_web_search(
        self,
        query: str,
        max_results: int
    ) -> Optional[Dict[str, Any]]:
        """Get news using web search (fallback)"""
        try:
            # Use DuckDuckGo news search
            from .web_search_service import WebSearchService
            
            web_service = WebSearchService()
            results, metadata = await web_service.search(
                query=f"{query} news",
                max_results=max_results,
                search_type="news",
                use_cache=False
            )
            
            articles = []
            for result in results:
                articles.append({
                    "title": result.get("title", ""),
                    "description": result.get("body", result.get("description", "")),
                    "url": result.get("href", result.get("url", "")),
                    "source": result.get("href", "").split("/")[2] if result.get("href") else "",
                    "published_at": ""
                })
            
            return {
                "query": query,
                "total_results": len(articles),
                "articles": articles,
                "source": "Web Search"
            }
        except Exception as e:
            logger.debug(f"Web search news failed: {e}")
        return None

