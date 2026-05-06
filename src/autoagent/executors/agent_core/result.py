from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoagent.executors.agent_core.device import Screenshot


@dataclass
class ActionResult:
    success: bool
    should_finish: bool
    message: str | None = None


@dataclass
class AgentStepRecord:
    step: int
    raw: str
    action: dict[str, Any]
    execution: ActionResult | None
    screenshot: Screenshot

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step": self.step,
            "raw": self.raw,
            "action": self.action,
        }
        if self.execution is not None:
            payload["execution"] = {
                "success": self.execution.success,
                "should_finish": self.execution.should_finish,
                "message": self.execution.message,
            }
        return payload


@dataclass
class AgentRunResult:
    finished: bool
    finish_message: str
    step_count: int
    stop_reason: str
    steps: list[AgentStepRecord] = field(default_factory=list)

