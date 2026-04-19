from __future__ import annotations

import asyncio
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from sandbox.core.service_container import AppServices, build_services
from sandbox.schemas.discussion import (
    DiscussionProgressEvent,
    MemberRuntimeOverride,
    RunDiscussionResponse,
    Scenario,
)


DISCUSSION_CANCELLED_MESSAGE = "Discussion cancelled during shutdown."


class DiscussionWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        service_factory: Callable[[], AppServices] = build_services,
        scenario_payload: dict,
        config_name: str,
        member_overrides_payload: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self.service_factory = service_factory
        self.scenario_payload = scenario_payload
        self.config_name = config_name
        self.member_overrides_payload = list(member_overrides_payload or [])
        self._cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            response = asyncio.run(self._run_async())
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(response)

    async def _run_async(self) -> RunDiscussionResponse:
        if self._cancel_requested:
            raise RuntimeError(DISCUSSION_CANCELLED_MESSAGE)

        services = self.service_factory()
        workbench_service = services.workbench_service
        try:
            scenario = Scenario.model_validate(self.scenario_payload)
            member_overrides = [
                MemberRuntimeOverride.model_validate(payload)
                for payload in self.member_overrides_payload
            ]
            return await workbench_service.run_discussion(
                scenario=scenario,
                config_name=self.config_name,
                member_overrides=member_overrides,
                progress_callback=self._handle_progress,
            )
        finally:
            await workbench_service.aclose()

    def _handle_progress(self, event: DiscussionProgressEvent) -> None:
        if self._cancel_requested:
            raise RuntimeError(DISCUSSION_CANCELLED_MESSAGE)
        self.progress.emit(event)
