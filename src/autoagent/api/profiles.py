from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.profiles.registry import (
    delete_profile as _delete,
)
from autoagent.profiles.registry import (
    list_profile_names,
    load_profile,
    load_profile_yaml,
    save_profile_yaml,
    validate_yaml,
)

router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(require_user)])


class ProfileBody(BaseModel):
    yaml: str


class ProfileSummary(BaseModel):
    name: str
    platform: str


class ProfileYamlResponse(BaseModel):
    name: str
    yaml: str


class ValidateResponse(BaseModel):
    ok: bool
    error: str | None = None


@router.get("", response_model=list[ProfileSummary])
async def list_profiles() -> list[ProfileSummary]:
    profiles: list[ProfileSummary] = []
    for name in list_profile_names():
        profile = load_profile(name)
        if profile is None:
            continue
        profiles.append(ProfileSummary(name=profile.name, platform=profile.platform))
    return profiles


@router.get("/{name}", response_model=ProfileYamlResponse)
async def get_profile(name: str) -> ProfileYamlResponse:
    text = load_profile_yaml(name)
    if text is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return ProfileYamlResponse(name=name, yaml=text)


@router.post("/validate", response_model=ValidateResponse)
async def validate_profile(body: ProfileBody) -> ValidateResponse:
    ok, err = validate_yaml(body.yaml)
    return ValidateResponse(ok=ok, error=err)


@router.post("/{name}", status_code=status.HTTP_201_CREATED)
async def create_profile(name: str, body: ProfileBody) -> dict:
    try:
        save_profile_yaml(name, body.yaml)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"name": name}


@router.put("/{name}")
async def update_profile(name: str, body: ProfileBody) -> dict:
    try:
        save_profile_yaml(name, body.yaml)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"name": name}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def del_profile(name: str) -> None:
    if not _delete(name):
        raise HTTPException(status_code=404, detail="profile not found")
