from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.devices.init_jobs import get_job, prune_old_jobs, start_job
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
from autoagent.profiles.schemas import AndroidProfile

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


class InitBody(BaseModel):
    serials: list[str]
    # None → use profile.init_reboot; true/false overrides it for this run.
    reboot: bool | None = None


@router.post("/{name}/initialize", status_code=202)
async def initialize_devices(name: str, body: InitBody) -> dict:
    """Kick off the profile's init_action on the given devices.

    Returns a job id immediately; poll GET /profiles/initialize/{job_id}
    for per-device progress. Async because init (esp. with reboot) can
    take minutes and must not block on a reverse-proxy timeout.
    """
    profile = load_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    if not isinstance(profile, AndroidProfile):
        raise HTTPException(
            status_code=422, detail="only android profiles support init playbooks"
        )
    if not body.serials:
        raise HTTPException(status_code=422, detail="no devices specified")
    prune_old_jobs()
    # Share the scheduler's device pool so init holds the same per-serial
    # lock a running sample would — they can't drive the device at once.
    from autoagent.api._deps import get_device_pool

    job = start_job(
        profile, body.serials, reboot_override=body.reboot, pool=get_device_pool()
    )
    return job.to_dict()


@router.get("/initialize/{job_id}")
async def get_init_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="init job not found")
    return job.to_dict()


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def del_profile(name: str) -> None:
    if not _delete(name):
        raise HTTPException(status_code=404, detail="profile not found")
