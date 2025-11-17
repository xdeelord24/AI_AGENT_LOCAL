from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter()


class SettingsRequest(BaseModel):
    ollama_url: Optional[str] = None
    ollama_direct_url: Optional[str] = None
    use_proxy: Optional[bool] = None
    default_model: Optional[str] = None


class SettingsResponse(BaseModel):
    ollama_url: str
    ollama_direct_url: str
    use_proxy: bool
    default_model: str
    current_model: str


async def get_ai_service(request: Request):
    """Dependency to get AI service instance"""
    return request.app.state.ai_service


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(ai_service = Depends(get_ai_service)):
    """Get current application settings"""
    try:
        return {
            "ollama_url": ai_service.ollama_url,
            "ollama_direct_url": ai_service.ollama_direct,
            "use_proxy": ai_service.use_proxy,
            "default_model": getattr(ai_service, "default_model", ai_service.current_model),
            "current_model": ai_service.current_model
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting settings: {str(e)}")


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    settings: SettingsRequest,
    ai_service = Depends(get_ai_service)
):
    """Update application settings"""
    try:
        # Update Ollama URL if provided
        if settings.ollama_url is not None:
            # Validate URL format
            if not (settings.ollama_url.startswith("http://") or settings.ollama_url.startswith("https://")):
                raise HTTPException(
                    status_code=400, 
                    detail="Ollama URL must start with http:// or https://"
                )
            ai_service.ollama_url = settings.ollama_url
            print(f"✅ Updated Ollama URL to: {settings.ollama_url}")
        
        # Update direct Ollama URL if provided
        if settings.ollama_direct_url is not None:
            if not (settings.ollama_direct_url.startswith("http://") or settings.ollama_direct_url.startswith("https://")):
                raise HTTPException(
                    status_code=400, 
                    detail="Ollama direct URL must start with http:// or https://"
                )
            ai_service.ollama_direct = settings.ollama_direct_url
            print(f"✅ Updated Ollama direct URL to: {settings.ollama_direct_url}")
        
        # Update proxy usage if provided
        if settings.use_proxy is not None:
            ai_service.use_proxy = settings.use_proxy
            print(f"✅ Updated use_proxy to: {settings.use_proxy}")
        
        # Update default model if provided
        if settings.default_model is not None:
            ai_service.default_model = settings.default_model
            ai_service.current_model = settings.default_model
            print(f"✅ Updated default model to: {settings.default_model}")
        
        # Persist updates before attempting connection tests so that user preferences
        # survive restarts even if validation fails.
        ai_service.save_settings()
        
        # Test connection after update
        is_connected = await ai_service.check_ollama_connection()
        if not is_connected:
            print("⚠️  Warning: Ollama connection failed after URL update")
        
        return {
            "ollama_url": ai_service.ollama_url,
            "ollama_direct_url": ai_service.ollama_direct,
            "use_proxy": ai_service.use_proxy,
            "default_model": getattr(ai_service, "default_model", ai_service.current_model),
            "current_model": ai_service.current_model
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating settings: {str(e)}")


@router.post("/settings/test-connection")
async def test_ollama_connection(ai_service = Depends(get_ai_service)):
    """Test connection to Ollama with current settings"""
    try:
        is_connected = await ai_service.check_ollama_connection()
        if is_connected:
            models = await ai_service.get_available_models()
            return {
                "connected": True,
                "message": "Successfully connected to Ollama",
                "available_models": models,
                "current_url": ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
            }
        else:
            return {
                "connected": False,
                "message": "Failed to connect to Ollama. Please check if Ollama is running and the URL is correct.",
                "current_url": ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
            }
    except Exception as e:
        return {
            "connected": False,
            "message": f"Error testing connection: {str(e)}",
            "current_url": ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
        }

