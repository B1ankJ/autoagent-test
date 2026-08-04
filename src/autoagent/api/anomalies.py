from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from autoagent.anomalies import store
from autoagent.auth.deps import require_user
from autoagent.models.api import AnomalyListResponse

router = APIRouter(prefix="/anomalies", tags=["anomalies"], dependencies=[Depends(require_user)])


@router.get("", response_model=AnomalyListResponse)
async def list_anomalies(
    type: str | None = None,
    target_profile: str | None = None,
    acknowledged: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AnomalyListResponse:
    items, total = await store.list_anomalies(
        type=type,
        target_profile=target_profile,
        acknowledged=acknowledged,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    return AnomalyListResponse(items=items, total=total)


@router.get("/count")
async def count_anomalies(acknowledged: bool | None = None) -> dict[str, int]:
    # Only the unacknowledged count is needed today (nav badge); the
    # acknowledged param is accepted for symmetry.
    if acknowledged is False:
        return {"count": await store.count_unacknowledged()}
    _, total = await store.list_anomalies(acknowledged=acknowledged, limit=1, offset=0)
    return {"count": total}


@router.post("/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(anomaly_id: int) -> dict[str, bool]:
    ok = await store.acknowledge(anomaly_id)
    if not ok:
        raise HTTPException(status_code=404, detail="anomaly not found")
    return {"acknowledged": True}
