import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("DID_ALLOW_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="set DID_ALLOW_NETWORK=1 to run real outbound network tests")
    for item in items:
        if "translation_network" in item.keywords:
            item.add_marker(skip)
