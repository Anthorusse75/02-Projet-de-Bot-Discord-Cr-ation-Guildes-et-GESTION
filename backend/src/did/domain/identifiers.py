from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuildId:
    """A Discord Guild snowflake kept as an integer inside Python."""

    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("guild_id must be a positive Discord snowflake")

    def to_api(self) -> str:
        """Serialize without JavaScript precision loss."""
        return str(self.value)
