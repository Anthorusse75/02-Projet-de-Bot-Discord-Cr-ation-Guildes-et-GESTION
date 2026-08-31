"""Structured Discord message model and Discord-limit validation (WP5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MessageModelViolation(ValueError):
    """A MessageModel would be rejected by Discord -- never send it."""


class DiscordLimits:
    MAX_CONTENT = 2000
    MAX_EMBEDS = 10
    MAX_EMBED_TITLE = 256
    MAX_EMBED_DESCRIPTION = 4096
    MAX_EMBED_FIELDS = 25
    MAX_EMBED_FIELD_NAME = 256
    MAX_EMBED_FIELD_VALUE = 1024
    MAX_EMBED_FOOTER = 2048
    MAX_EMBED_AUTHOR_NAME = 256
    MAX_TOTAL_EMBED_CHARS = 6000
    MAX_ACTION_ROWS = 5
    MAX_BUTTONS_PER_ROW = 5


class ButtonStyle(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    SUCCESS = "SUCCESS"
    DANGER = "DANGER"
    LINK = "LINK"


@dataclass(frozen=True, slots=True)
class EmbedField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True, slots=True)
class Embed:
    title: str | None = None
    description: str | None = None
    url: str | None = None
    color: int | None = None
    footer_text: str | None = None
    author_name: str | None = None
    fields: tuple[EmbedField, ...] = ()

    def character_budget(self) -> int:
        total = len(self.title or "") + len(self.description or "")
        total += len(self.footer_text or "") + len(self.author_name or "")
        for f in self.fields:
            total += len(f.name) + len(f.value)
        return total


@dataclass(frozen=True, slots=True)
class ComponentButton:
    label: str
    style: ButtonStyle = ButtonStyle.PRIMARY
    custom_id: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ComponentActionRow:
    buttons: tuple[ComponentButton, ...] = ()


@dataclass(frozen=True, slots=True)
class MessageModel:
    content: str = ""
    embeds: tuple[Embed, ...] = field(default=())
    action_rows: tuple[ComponentActionRow, ...] = field(default=())


def validate_message_model(model: MessageModel) -> None:
    """Raise :class:`MessageModelViolation` for anything Discord would reject.

    Called before every create AND edit -- an over-limit MessageModel must
    never reach the Discord adapter.
    """
    if not model.content.strip() and not model.embeds:
        raise MessageModelViolation("message must have non-blank content or at least one embed")
    if len(model.content) > DiscordLimits.MAX_CONTENT:
        raise MessageModelViolation(
            f"content exceeds {DiscordLimits.MAX_CONTENT} characters ({len(model.content)})"
        )
    if len(model.embeds) > DiscordLimits.MAX_EMBEDS:
        raise MessageModelViolation(f"more than {DiscordLimits.MAX_EMBEDS} embeds")

    total_embed_chars = 0
    for index, embed in enumerate(model.embeds):
        if embed.title and len(embed.title) > DiscordLimits.MAX_EMBED_TITLE:
            raise MessageModelViolation(f"embed[{index}].title exceeds Discord limit")
        if embed.description and len(embed.description) > DiscordLimits.MAX_EMBED_DESCRIPTION:
            raise MessageModelViolation(f"embed[{index}].description exceeds Discord limit")
        if embed.footer_text and len(embed.footer_text) > DiscordLimits.MAX_EMBED_FOOTER:
            raise MessageModelViolation(f"embed[{index}].footer_text exceeds Discord limit")
        if embed.author_name and len(embed.author_name) > DiscordLimits.MAX_EMBED_AUTHOR_NAME:
            raise MessageModelViolation(f"embed[{index}].author_name exceeds Discord limit")
        if len(embed.fields) > DiscordLimits.MAX_EMBED_FIELDS:
            raise MessageModelViolation(f"embed[{index}] has more than 25 fields")
        for field_index, embed_field in enumerate(embed.fields):
            if not embed_field.name.strip() or not embed_field.value.strip():
                raise MessageModelViolation(f"embed[{index}].fields[{field_index}] is blank")
            if len(embed_field.name) > DiscordLimits.MAX_EMBED_FIELD_NAME:
                raise MessageModelViolation(f"embed[{index}].fields[{field_index}].name too long")
            if len(embed_field.value) > DiscordLimits.MAX_EMBED_FIELD_VALUE:
                raise MessageModelViolation(
                    f"embed[{index}].fields[{field_index}].value too long"
                )
        total_embed_chars += embed.character_budget()

    if total_embed_chars > DiscordLimits.MAX_TOTAL_EMBED_CHARS:
        raise MessageModelViolation(
            f"combined embed character budget exceeds "
            f"{DiscordLimits.MAX_TOTAL_EMBED_CHARS} ({total_embed_chars})"
        )

    if len(model.action_rows) > DiscordLimits.MAX_ACTION_ROWS:
        raise MessageModelViolation(f"more than {DiscordLimits.MAX_ACTION_ROWS} action rows")
    for row_index, row in enumerate(model.action_rows):
        if not row.buttons:
            raise MessageModelViolation(f"action_rows[{row_index}] has no buttons")
        if len(row.buttons) > DiscordLimits.MAX_BUTTONS_PER_ROW:
            raise MessageModelViolation(f"action_rows[{row_index}] has more than 5 buttons")
        for button_index, button in enumerate(row.buttons):
            if not button.label.strip():
                raise MessageModelViolation(
                    f"action_rows[{row_index}].buttons[{button_index}] has a blank label"
                )
            if button.style is ButtonStyle.LINK:
                if not button.url:
                    raise MessageModelViolation("LINK buttons require a url")
                if button.custom_id:
                    raise MessageModelViolation("LINK buttons must not carry a custom_id")
            else:
                if not button.custom_id:
                    raise MessageModelViolation(
                        "non-LINK buttons require a custom_id"
                    )
                if button.url:
                    raise MessageModelViolation("non-LINK buttons must not carry a url")
