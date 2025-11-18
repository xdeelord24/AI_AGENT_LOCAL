from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter()


class SettingsRequest(BaseModel):
    ollama_url: Optional[str] = None
    ollama_direct_url: Optional[str] = None
    use_proxy: Optional[bool] = None
    default_model: Optional[str] = None
    provider: Optional[str] = None
    hf_model: Optional[str] = None
    hf_base_url: Optional[str] = None
    hf_api_key: Optional[str] = None


class SettingsResponse(BaseModel):
    ollama_url: str
    ollama_direct_url: str
    use_proxy: bool
    default_model: str
    current_model: str
    provider: str
    hf_model: Optional[str]
    hf_base_url: Optional[str]
    hf_api_key_set: bool


async def get_ai_service(request: Request):
    """Dependency to get AI service instance"""
    return request.app.state.ai_service


@router.get("", response_model=SettingsResponse)
async def get_settings(ai_service = Depends(get_ai_service)):
    """Get current application settings"""
    try:
        hf_base_url = getattr(ai_service, "hf_base_url", "") or ""
        if isinstance(hf_base_url, str) and hf_base_url.strip().lower() == ai_service.HF_DEFAULT_API_BASE.lower():
            hf_base_url = ""

        return {
            "ollama_url": ai_service.ollama_url,
            "ollama_direct_url": ai_service.ollama_direct,
            "use_proxy": ai_service.use_proxy,
            "default_model": getattr(ai_service, "default_model", ai_service.current_model),
            "current_model": ai_service.current_model,
            "provider": getattr(ai_service, "provider", "ollama"),
            "hf_model": getattr(ai_service, "hf_model", None),
            "hf_base_url": hf_base_url,
            "hf_api_key_set": bool(getattr(ai_service, "hf_api_key", "") or "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting settings: {str(e)}")


@router.put("", response_model=SettingsResponse)
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

        # Update provider if provided
        if settings.provider is not None:
            provider = settings.provider.lower()
            if provider not in ("ollama", "huggingface"):
                raise HTTPException(
                    status_code=400,
                    detail="Provider must be either 'ollama' or 'huggingface'"
                )
            ai_service.provider = provider
            if provider == "huggingface":
                ai_service.current_model = ai_service.hf_model or ai_service.current_model
            else:
                ai_service.current_model = ai_service.default_model
            print(f"✅ Updated provider to: {provider}")

        # Update Hugging Face model/base URL/API key if provided
        hf_settings_changed = False
        if settings.hf_model is not None:
            ai_service.hf_model = settings.hf_model
            if ai_service.provider == "huggingface":
                ai_service.current_model = settings.hf_model
            hf_settings_changed = True
            print(f"✅ Updated Hugging Face model to: {settings.hf_model}")

        if settings.hf_base_url is not None:
            normalized_base = (settings.hf_base_url or "").strip()
            if normalized_base.lower() == ai_service.HF_DEFAULT_API_BASE.lower():
                normalized_base = ""
            ai_service.hf_base_url = normalized_base
            hf_settings_changed = True
            print(f"✅ Updated Hugging Face base URL to: {normalized_base or '[default host]'}")

        if settings.hf_api_key is not None:
            ai_service.hf_api_key = settings.hf_api_key
            hf_settings_changed = True
            print("✅ Updated Hugging Face API key")

        if hf_settings_changed:
            ai_service.reset_hf_client()
        
        # Persist updates before attempting connection tests so that user preferences
        # survive restarts even if validation fails.
        ai_service.save_settings()
        
        # Test connection after update
        is_connected = await ai_service.check_provider_connection(force=True)
        if not is_connected:
            print("⚠️  Warning: Provider connection failed after settings update")
        
        hf_base_url = (ai_service.hf_base_url or "")
        if hf_base_url.strip().lower() == ai_service.HF_DEFAULT_API_BASE.lower():
            hf_base_url = ""

        return {
            "ollama_url": ai_service.ollama_url,
            "ollama_direct_url": ai_service.ollama_direct,
            "use_proxy": ai_service.use_proxy,
            "default_model": getattr(ai_service, "default_model", ai_service.current_model),
            "current_model": ai_service.current_model,
            "provider": getattr(ai_service, "provider", "ollama"),
            "hf_model": getattr(ai_service, "hf_model", None),
            "hf_base_url": hf_base_url,
            "hf_api_key_set": bool(getattr(ai_service, "hf_api_key", "") or "")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating settings: {str(e)}")


@router.post("/test-connection")
async def test_ollama_connection(ai_service = Depends(get_ai_service)):
    """Test connection to Ollama with current settings"""
    hf_base_url = ""
    try:
        is_connected = await ai_service.check_provider_connection(force=True)
        provider = getattr(ai_service, "provider", "ollama")
        hf_base_url = (ai_service.hf_base_url or "")
        if hf_base_url.strip().lower() == ai_service.HF_DEFAULT_API_BASE.lower():
            hf_base_url = ""

        if is_connected:
            models = await ai_service.get_available_models()
            return {
                "connected": True,
                "message": "Successfully connected to provider" if provider == "ollama" else "Hugging Face settings look good",
                "available_models": models,
                "current_url": (
                    ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
                ) if provider == "ollama" else (hf_base_url or ai_service.HF_DEFAULT_API_BASE)
            }
        else:
            return {
                "connected": False,
                "message": (
                    "Failed to connect to Ollama. Please check if Ollama is running and the URL is correct."
                    if provider == "ollama"
                    else "Hugging Face settings appear incomplete. Please verify your API key and model."
                ),
                "current_url": (
                    ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
                ) if provider == "ollama" else (hf_base_url or ai_service.HF_DEFAULT_API_BASE)
            }
    except Exception as e:
        return {
            "connected": False,
            "message": f"Error testing connection: {str(e)}",
            "current_url": (
                ai_service.ollama_url if ai_service.use_proxy else ai_service.ollama_direct
            ) if getattr(ai_service, "provider", "ollama") == "ollama" else (hf_base_url or ai_service.HF_DEFAULT_API_BASE)
        }

