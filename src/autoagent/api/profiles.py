from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.profiles.registry import (
    delete_profile as _delete,
)
from autoagent.profiles.registry import (
    get_profile_devices,
    list_profile_names,
    load_profile,
    load_profile_yaml,
    save_profile_yaml,
    set_profile_devices,
    validate_yaml,
)

router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(require_user)])


class ProfileBody(BaseModel):
    yaml: str


class ProfileSummary(BaseModel):
    name: str
    platform: str
    # Effective device pool (serial + serials merged). Empty for
    # non-android platforms or an unbound android profile.
    serials: list[str] = []


class DeviceBindingBody(BaseModel):
    serials: list[str]


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
        serial = getattr(profile, "serial", None)
        serials = list(getattr(profile, "serials", None) or [])
        if serial and serial not in serials:
            serials = [serial, *serials]
        profiles.append(
            ProfileSummary(name=profile.name, platform=profile.platform, serials=serials)
        )
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


@router.get("/{name}/devices")
async def get_devices(name: str) -> dict:
    if load_profile_yaml(name) is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return {"name": name, "serials": get_profile_devices(name)}


@router.put("/{name}/devices")
async def put_devices(name: str, body: DeviceBindingBody) -> dict:
    try:
        set_profile_devices(name, body.serials)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="profile not found") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"name": name, "serials": get_profile_devices(name)}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def del_profile(name: str) -> None:
    if not _delete(name):
        raise HTTPException(status_code=404, detail="profile not found")
