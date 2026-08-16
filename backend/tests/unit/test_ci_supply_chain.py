import re
from pathlib import Path

EXPECTED_ACTIONS = {
    "actions/checkout": ("d23441a48e516b6c34aea4fa41551a30e30af803", "v6.1.0"),
    "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6.3.0"),
    "astral-sh/setup-uv": ("c771a70e6277c0a99b617c7a806ffedaca235ff9", "v9.0.0"),
    "actions/setup-node": ("249970729cb0ef3589644e2896645e5dc5ba9c38", "v6.5.0"),
    "actions/upload-artifact": ("b7c566a772e6b6bfb58ed0dc250532a479d7789f", "v6.0.0"),
}


def test_ci_actions_are_pinned_to_reviewed_full_commit_shas() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    matches = re.findall(r"uses: ([^@\s]+)@([0-9a-f]{40}) # (v\d+\.\d+\.\d+)", workflow)
    actual = {action: (commit, version) for action, commit, version in matches}

    assert actual == EXPECTED_ACTIONS
