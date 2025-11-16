@echo off
echo Fixing Ollama CORS Issues...
echo.

echo Setting OLLAMA_ORIGINS environment variable...
set OLLAMA_ORIGINS=*

echo Starting Ollama with CORS enabled...
echo This will allow the frontend to connect to Ollama directly.
echo.

ollama serve

pause
