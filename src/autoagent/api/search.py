from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from autoagent.auth.deps import require_user
from autoagent.models.api import SampleSearchResponse
from autoagent.storage.samples import search_samples_by_response

router = APIRouter(prefix="/samples", tags=["search"], dependencies=[Depends(require_user)])


@router.get("/search", response_model=SampleSearchResponse)
async def search_responses(
    q: str = Query(..., min_length=2),
    target_profile: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SampleSearchResponse:
    items, total = await search_samples_by_response(
        q.strip(), target_profile=target_profile, limit=limit, offset=offset
    )
    return SampleSearchResponse(items=items, total=total)
