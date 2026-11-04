"""
Antigravity Model List Router - Handles model list requests
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.utils import (
    get_base_model_from_feature_model,
    authenticate_flexible
)
from src.api.antigravity import fetch_available_models
from src.router.base_router import create_gemini_model_list, create_openai_model_list
from src.models import model_to_dict
from log import log

router = APIRouter()


async def get_antigravity_models_with_features():
    """
    Retrieve Antigravity model list with feature prefixes.
    
    Returns:
        List of models including anti-truncate- prefixed variants.
    """
    base_models_data = await fetch_available_models()
    
    if not base_models_data:
        log.warning("[ANTIGRAVITY MODEL LIST] Unable to fetch models, returning empty list")
        return []
    
    base_model_ids = [model['id'] for model in base_models_data if 'id' in model]
    
    models = []
    for base_model in base_model_ids:
        models.append(base_model)
        models.append(f"anti-truncate-{base_model}")
    
    log.info(f"[ANTIGRAVITY MODEL LIST] Generated {len(models)} models (including feature prefixes)")
    return models


@router.get("/v1beta/models")
async def list_gemini_models(token: str = Depends(authenticate_flexible)):
    """
    Return model list in Gemini format with anti-truncation prefixes.
    """
    models = await get_antigravity_models_with_features()
    log.info("[ANTIGRAVITY MODEL LIST] Returning Gemini format")
    return JSONResponse(content=create_gemini_model_list(
        models,
        base_name_extractor=get_base_model_from_feature_model
    ))


@router.get("/v1/models")
async def list_openai_models(token: str = Depends(authenticate_flexible)):
    """
    Return model list in OpenAI format with anti-truncation prefixes.
    """
    models = await get_antigravity_models_with_features()
    log.info("[ANTIGRAVITY MODEL LIST] Returning OpenAI format")
    model_list = create_openai_model_list(models, owned_by="google")
    return JSONResponse(content={
        "object": "list",
        "data": [model_to_dict(model) for model in model_list.data]
    })
