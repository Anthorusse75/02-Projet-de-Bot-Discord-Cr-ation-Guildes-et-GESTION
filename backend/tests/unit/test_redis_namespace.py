import pytest

from did.infrastructure.redis import guild_namespace


def test_guild_namespace_is_mandatory() -> None:
    assert guild_namespace(123).key("cache", "channels") == "did:guild:123:cache:channels"


@pytest.mark.parametrize("segment", ["", "Uppercase", "space key", "../escape"])
def test_unsafe_redis_segments_are_rejected(segment: str) -> None:
    with pytest.raises(ValueError):
        guild_namespace(123).key(segment)


def test_invalid_guild_namespace_is_rejected() -> None:
    with pytest.raises(ValueError, match="guild_id"):
        guild_namespace(0)
