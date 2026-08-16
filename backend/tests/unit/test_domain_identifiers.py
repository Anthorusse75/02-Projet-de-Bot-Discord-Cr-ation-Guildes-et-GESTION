import pytest

from did.domain.identifiers import GuildId


def test_guild_id_serializes_to_string_at_api_boundary() -> None:
    snowflake = GuildId(123456789012345678)
    assert snowflake.to_api() == "123456789012345678"


def test_guild_id_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="positive"):
        GuildId(0)
