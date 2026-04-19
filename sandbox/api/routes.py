from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sandbox.application.workbench_service import WorkbenchService
from sandbox.schemas.discussion import RunDiscussionRequest, RunDiscussionResponse
from sandbox.skill_loader import SkillError


router = APIRouter()


def get_workbench_service(request: Request) -> WorkbenchService:
    return request.app.state.services.workbench_service


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/v1/discussions/run", response_model=RunDiscussionResponse)
async def run_discussion(
    request_body: RunDiscussionRequest,
    workbench_service: WorkbenchService = Depends(get_workbench_service),
) -> RunDiscussionResponse:
    try:
        return await workbench_service.run_discussion(
            scenario=request_body.scenario,
            config_name=request_body.config_name,
            member_overrides=request_body.member_overrides,
        )
    except (FileNotFoundError, ValueError, SkillError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/sessions/{session_id}", response_model=RunDiscussionResponse)
async def get_session(
    session_id: str,
    workbench_service: WorkbenchService = Depends(get_workbench_service),
) -> RunDiscussionResponse:
    try:
        return workbench_service.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
