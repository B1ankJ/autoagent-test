from fastapi import APIRouter, Depends, HTTPException

from autoagent.auth.deps import require_user
from autoagent.models.api import DefaultsConfig, VLMConfig
from autoagent.storage.configs import get_config, put_config

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_user)])


@router.get("/vlm", response_model=VLMConfig | None)
async def get_vlm() -> VLMConfig | None:
    v = await get_config("vlm")
    if v is None:
        return None
    return VLMConfig.model_validate(v)


@router.put("/vlm", response_model=VLMConfig)
async def put_vlm(body: VLMConfig) -> VLMConfig:
    await put_config("vlm", body.model_dump())
    return body


@router.get("/defaults", response_model=DefaultsConfig)
async def get_defaults() -> DefaultsConfig:
    v = await get_config("defaults")
    return DefaultsConfig.model_validate(v) if v else DefaultsConfig()


@router.put("/defaults", response_model=DefaultsConfig)
async def put_defaults(body: DefaultsConfig) -> DefaultsConfig:
    await put_config("defaults", body.model_dump())
    return body
