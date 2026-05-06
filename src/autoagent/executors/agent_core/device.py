# src/autoagent/executors/agent_core/device.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Screenshot:
    base64_data: str
    width: int
    height: int


class Device(ABC):
    @abstractmethod
    def capture(self) -> Screenshot: ...

    @abstractmethod
    def execute_action(self, action: dict) -> None:
        """Execute a parsed action dict. Raises on hard failure."""
