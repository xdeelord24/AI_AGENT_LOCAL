#!/usr/bin/env python3
"""
Ollama CORS Proxy Server for Offline AI Agent
This proxy server helps bypass CORS issues when accessing Ollama API from the frontend.
"""

from flask import Flask, request, jsonify, stream_with_context
from flask_cors import CORS
import requests
import json
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'localhost')
OLLAMA_PORT = os.getenv('OLLAMA_PORT', '11434')
OLLAMA_BASE_URL = f'http://{OLLAMA_HOST}:{OLLAMA_PORT}'

@app.route('/api/generate', methods=['POST'])
def proxy_generate():
    """Proxy requests to Ollama's generate endpoint"""
    try:
        # Get the request data
        data = request.get_json()
        
        # Add headers for streaming if needed
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Forward request to Ollama
        response = requests.post(
            f'{OLLAMA_BASE_URL}/api/generate',
            json=data,
            headers=headers,
            timeout=300,  # 5 minute timeout
            stream=data.get('stream', False)
        )
        
        # Handle streaming responses
        if data.get('stream', False):
            def generate():
                try:
                    for line in response.iter_lines():
                        if line:
                            yield line.decode('utf-8') + '\n'
                except Exception as e:
                    yield f'{{"error": "Streaming error: {str(e)}"}}\n'
            
            return app.response_class(
                stream_with_context(generate()),
                mimetype='application/json',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type'
                }
            )
        else:
            # Handle non-streaming responses
            return jsonify(response.json())
            
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout - Ollama server may be busy'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'Cannot connect to Ollama server at {OLLAMA_BASE_URL}'}), 503
    except Exception as e:
        return jsonify({'error': f'Proxy error: {str(e)}'}), 500

@app.route('/api/tags', methods=['GET'])
def proxy_tags():
    """Proxy requests to Ollama's tags endpoint"""
    try:
        response = requests.get(f'{OLLAMA_BASE_URL}/api/tags', timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': f'Failed to get models: {str(e)}'}), 500

@app.route('/api/show', methods=['POST'])
def proxy_show():
    """Proxy requests to Ollama's show endpoint"""
    try:
        data = request.get_json()
        response = requests.post(f'{OLLAMA_BASE_URL}/api/show', json=data, timeout=30)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': f'Failed to show model info: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        response = requests.get(f'{OLLAMA_BASE_URL}/api/tags', timeout=5)
        return jsonify({
            'status': 'healthy',
            'ollama_server': OLLAMA_BASE_URL,
            'ollama_status': 'connected' if response.status_code == 200 else 'error'
        })
    except:
        return jsonify({
            'status': 'unhealthy',
            'ollama_server': OLLAMA_BASE_URL,
            'ollama_status': 'disconnected'
        }), 503

@app.route('/')
def index():
    """Simple index page"""
    return '''
    <h1>Ollama CORS Proxy for Offline AI Agent</h1>
    <p>This proxy server helps bypass CORS issues when accessing Ollama API.</p>
    <h2>Endpoints:</h2>
    <ul>
        <li><code>POST /api/generate</code> - Generate responses</li>
        <li><code>GET /api/tags</code> - List available models</li>
        <li><code>POST /api/show</code> - Show model information</li>
        <li><code>GET /health</code> - Health check</li>
    </ul>
    <h2>Usage:</h2>
    <p>This proxy is automatically used by the Offline AI Agent backend.</p>
    '''

if __name__ == '__main__':
    print(f"Starting Ollama CORS Proxy Server...")
    print(f"Ollama Server: {OLLAMA_BASE_URL}")
    print(f"Proxy Server: http://0.0.0.0:5000")
    print(f"This proxy will be used by the Offline AI Agent backend.")
    
    app.run(
        host='0.0.0.0',  # Allow access from any IP
        port=5000,
        debug=False
    )
