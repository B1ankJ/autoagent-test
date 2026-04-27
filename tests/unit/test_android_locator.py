from autoagent.executors.android_locator import selector_kwargs
from autoagent.profiles.schemas import Locator


def test_selector_kwargs_maps_resource_id() -> None:
    assert selector_kwargs(Locator(type="resource_id", value="com.demo:id/input")) == {
        "resourceId": "com.demo:id/input"
    }
