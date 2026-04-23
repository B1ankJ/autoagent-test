from __future__ import annotations

from typing import Any

from autoagent.profiles.schemas import Locator


def selector_kwargs(locator: Locator | dict[str, str]) -> dict[str, str]:
    if isinstance(locator, dict):
        locator = Locator.model_validate(locator)
    if locator.type == "resource_id":
        return {"resourceId": locator.value}
    if locator.type == "text":
        return {"text": locator.value}
    if locator.type == "xpath":
        return {"xpath": locator.value}
    if locator.type == "class":
        return {"className": locator.value}
    raise ValueError(f"unsupported direct selector type: {locator.type}")


def resolve_target(device: Any, locator: Locator | dict[str, str]):
    if isinstance(locator, dict):
        locator = Locator.model_validate(locator)
    if locator.type == "xpath":
        return device.xpath(locator.value)
    return device(**selector_kwargs(locator))
