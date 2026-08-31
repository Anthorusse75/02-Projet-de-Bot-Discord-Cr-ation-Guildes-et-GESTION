"""REQ-MSG-031: every edit explicitly supplies its attachment preservation
policy, alongside allowed_mentions -- never an implicit Discord default that
could silently drop or replace existing attachments.
"""

from __future__ import annotations

from dataclasses import dataclass

from did.domain.campaigns import AttachmentPolicy
from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.message_model import MessageModel, validate_message_model

__all__ = ["AttachmentPolicy", "EditPayload"]


@dataclass(frozen=True, slots=True)
class EditPayload:
    message_model: MessageModel
    allowed_mentions: CompiledAllowedMentions
    attachment_policy: AttachmentPolicy

    def to_discord_kwargs(self) -> dict[str, object]:
        """Build the explicit discord.py ``Message.edit`` keyword arguments.

        ``attachments`` is only ever set explicitly: ``REMOVE_ALL`` sends an
        empty list (discord.py's documented way to clear attachments on
        edit), ``PRESERVE_EXISTING`` omits the key entirely (discord.py's
        documented way to leave existing attachments untouched), and
        ``REPLACE_ALL`` is the caller's responsibility to populate with new
        ``discord.File``/``discord.Attachment`` objects before sending --
        this compiler only fixes the *policy*, never invents file content.
        """
        validate_message_model(self.message_model)
        kwargs: dict[str, object] = {
            "content": self.message_model.content,
            "allowed_mentions": self.allowed_mentions.to_discord_payload(),
        }
        if self.attachment_policy is AttachmentPolicy.REMOVE_ALL:
            kwargs["attachments"] = []
        # PRESERVE_EXISTING: omit `attachments` entirely.
        # REPLACE_ALL: caller must add `attachments=[...]` with real File
        # objects before dispatch; this module cannot fabricate them.
        return kwargs
