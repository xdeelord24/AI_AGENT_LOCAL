# Location, Weather, and News Features

This AI Agent now includes location detection, weather, and news capabilities through MCP (Model Context Protocol) tools.

## Features

### 1. Location Detection (`get_user_location`)
- Automatically detects user location based on IP address
- Returns city, region, country, coordinates, timezone, and IP address
- Uses free IP geolocation APIs (ipapi.co and ip-api.com)
- No API key required for basic location detection

### 2. Weather Information (`get_weather`)
- Get current weather for any city or coordinates
- Supports both metric (Celsius) and imperial (Fahrenheit) units
- Returns temperature, conditions, humidity, wind speed, pressure, and visibility
- Uses OpenWeatherMap API (if API key provided) or wttr.in (free fallback)

### 3. News Articles (`get_news`)
- Get location-based news articles
- Can filter by city, country, or search query
- Returns recent news with titles, descriptions, sources, and URLs
- Uses NewsAPI (if API key provided) or web search fallback

## Usage Examples

### Example 1: Get User Location and Weather
```
User: "What's the weather like where I am?"

AI will:
1. Call get_user_location() to detect your location
2. Call get_weather() with your city/coordinates
3. Provide current weather information
```

### Example 2: Get Weather for a Specific City
```
User: "What's the weather in London?"

AI will:
1. Call get_weather(city="London")
2. Provide current weather for London
```

### Example 3: Get Local News
```
User: "Show me the latest news in my area"

AI will:
1. Call get_user_location() to detect your location
2. Call get_news(city="Your City", country="Your Country")
3. Provide recent news articles
```

### Example 4: Get News for a Specific Location
```
User: "What's happening in New York?"

AI will:
1. Call get_news(city="New York", country="US")
2. Provide recent news articles from New York
```

## Configuration

### Optional API Keys (for enhanced features)

While the services work without API keys using free fallback APIs, you can optionally configure:

1. **OpenWeatherMap API Key** (for better weather data)
   - Get free API key at: https://openweathermap.org/api
   - Set environment variable: `OPENWEATHER_API_KEY=your_key_here`

2. **NewsAPI Key** (for better news results)
   - Get free API key at: https://newsapi.org/
   - Set environment variable: `NEWS_API_KEY=your_key_here`

### Environment Variables

Add to your `.env` file or set as environment variables:

```bash
# Optional: For enhanced weather data
OPENWEATHER_API_KEY=your_openweather_api_key

# Optional: For enhanced news results
NEWS_API_KEY=your_newsapi_key
```

## How It Works

### Location Detection
- Uses IP geolocation services (ipapi.co, ip-api.com)
- Automatically detects location from connection IP
- Caches results for 1 hour to reduce API calls

### Weather Service
- **Primary**: OpenWeatherMap API (if API key configured)
- **Fallback**: wttr.in (free, no API key required)
- Caches weather data for 10 minutes

### News Service
- **Primary**: NewsAPI (if API key configured)
- **Fallback**: Web search with DuckDuckGo news search
- Caches news data for 30 minutes

## MCP Tools Available

The following MCP tools are automatically available to the AI:

1. **`get_user_location`**
   - Parameters: `ip_address` (optional)
   - Returns: Location information (city, country, coordinates, timezone)

2. **`get_weather`**
   - Parameters: `city` (or `latitude`/`longitude`), `units` (optional, default: "metric")
   - Returns: Current weather information

3. **`get_news`**
   - Parameters: `city` (optional), `country` (optional), `query` (optional), `max_results` (optional, default: 10)
   - Returns: News articles for the specified location/query

## Privacy & Security

- Location detection uses IP geolocation (approximate location, not exact address)
- No personal data is stored or transmitted
- All API calls use HTTPS
- Cache data is stored locally and expires automatically

## Troubleshooting

### Location Not Detected
- Check internet connection
- IP geolocation services may be temporarily unavailable
- Try again after a few moments

### Weather Not Available
- Check internet connection
- Verify city name spelling
- Weather APIs may have rate limits

### News Not Available
- Check internet connection
- News APIs may have rate limits
- Try specifying a more specific location or query

## Technical Details

- **Location Cache TTL**: 1 hour
- **Weather Cache TTL**: 10 minutes
- **News Cache TTL**: 30 minutes
- **Rate Limiting**: Built-in to prevent API abuse
- **Error Handling**: Graceful fallbacks to alternative services

## Future Enhancements

- Weather forecasts (not just current conditions)
- Historical weather data
- More news sources
- Location history tracking (optional)
- Custom location preferences

