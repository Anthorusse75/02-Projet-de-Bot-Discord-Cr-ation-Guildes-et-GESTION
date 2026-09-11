"""REQ-MSG-031: every edit explicitly supplies its attachment preservation
policy, alongside allowed_mentions -- never an implicit Discord default that
could silently drop or replace existing attachments.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from did.domain.campaigns import AttachmentPolicy
from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.message_model import MessageModel, validate_message_model

__all__ = ["AttachmentPolicy", "EditPayload", "NewAttachment"]


@dataclass(frozen=True, slots=True)
class NewAttachment:
    """A replacement attachment for REPLACE_ALL -- raw bytes, not a
    discord.py type, so this module stays free of the discord.py dependency;
    the adapter (``did.infrastructure.discord_message_sender``) converts
    this to a real ``discord.File`` at dispatch time."""

    filename: str
    content: bytes
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.filename.strip():
            raise ValueError("filename must not be blank")
        if not self.content:
            raise ValueError("content must not be empty")


@dataclass(frozen=True, slots=True)
class EditPayload:
    message_model: MessageModel
    allowed_mentions: CompiledAllowedMentions
    attachment_policy: AttachmentPolicy
    #: Required (non-empty) when attachment_policy is REPLACE_ALL; must be
    #: empty for PRESERVE_EXISTING/REMOVE_ALL. External-review fix: REPLACE_ALL
    #: previously fell through to the same no-op as PRESERVE_EXISTING with no
    #: way to actually supply replacement files -- silently NOT replacing
    #: anything despite the caller's explicit intent.
    new_attachments: tuple[NewAttachment, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.attachment_policy is AttachmentPolicy.REPLACE_ALL and not self.new_attachments:
            raise ValueError(
                "REPLACE_ALL requires at least one new_attachments entry -- "
                "it is never silently treated as PRESERVE_EXISTING"
            )
        if self.attachment_policy is not AttachmentPolicy.REPLACE_ALL and self.new_attachments:
            raise ValueError("new_attachments is only meaningful with REPLACE_ALL")

    def to_discord_kwargs(self) -> dict[str, object]:
        """Build the explicit discord.py ``Message.edit`` keyword arguments.

        ``attachments``/``new_attachments`` is only ever set explicitly:
        ``REMOVE_ALL`` sends an empty ``attachments`` list (discord.py's
        documented way to clear attachments on edit), ``PRESERVE_EXISTING``
        omits the key entirely (discord.py's documented way to leave
        existing attachments untouched), and ``REPLACE_ALL`` carries the
        caller-supplied ``new_attachments`` under its own key so the adapter
        builds real ``discord.File`` objects from them -- never silently
        equivalent to PRESERVE_EXISTING.
        """
        validate_message_model(self.message_model)
        kwargs: dict[str, object] = {
            "content": self.message_model.content,
            "allowed_mentions": self.allowed_mentions.to_discord_payload(),
        }
        if self.attachment_policy is AttachmentPolicy.REMOVE_ALL:
            kwargs["attachments"] = []
        elif self.attachment_policy is AttachmentPolicy.REPLACE_ALL:
            kwargs["new_attachments"] = self.new_attachments
        # PRESERVE_EXISTING: omit the key entirely.
        return kwargs
