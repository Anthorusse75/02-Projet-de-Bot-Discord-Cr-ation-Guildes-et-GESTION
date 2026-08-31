"""Real discord.py-backed DiscordMessageSender adapter (WP5/WP6).

Built and parameter-checked against the actual installed
``discord.py==2.7.1`` signatures (``Messageable.send``, ``Message.edit``,
``AllowedMentions.__init__``, ``Embed`` builder methods) -- not assumed.
Live send/edit/delete behavior itself (as opposed to the parameter shapes)
is exercised by the WP16 Discord sandbox qualification, not by an offline
unit test; discord.py's own network layer is not something this repository
re-tests.
"""

from __future__ import annotations

from typing import Any

import discord

from did.domain.message_sending import DiscordSendError, DiscordSendOutcome
from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.edit_payload import EditPayload
from did.messaging.message_model import ComponentActionRow, Embed, MessageModel


def _build_discord_embed(embed: Embed) -> discord.Embed:
    result = discord.Embed(
        title=embed.title,
        description=embed.description,
        url=embed.url,
        colour=embed.color,
    )
    if embed.footer_text:
        result.set_footer(text=embed.footer_text)
    if embed.author_name:
        result.set_author(name=embed.author_name)
    for field in embed.fields:
        result.add_field(name=field.name, value=field.value, inline=field.inline)
    return result


def _build_discord_allowed_mentions(compiled: CompiledAllowedMentions) -> discord.AllowedMentions:
    return discord.AllowedMentions(
        everyone="everyone" in compiled.parse,
        users=[discord.Object(id=u) for u in compiled.users] if compiled.users else False,
        roles=[discord.Object(id=r) for r in compiled.roles] if compiled.roles else False,
        replied_user=compiled.replied_user,
    )


def _build_discord_views(rows: tuple[ComponentActionRow, ...]) -> discord.ui.View | None:
    if not rows:
        return None
    view = discord.ui.View(timeout=None)
    for row in rows:
        for button in row.buttons:
            view.add_item(
                discord.ui.Button(
                    label=button.label,
                    style=_button_style(button.style.value),
                    custom_id=button.custom_id,
                    url=button.url,
                )
            )
    return view


def _button_style(style: str) -> discord.ButtonStyle:
    return {
        "PRIMARY": discord.ButtonStyle.primary,
        "SECONDARY": discord.ButtonStyle.secondary,
        "SUCCESS": discord.ButtonStyle.success,
        "DANGER": discord.ButtonStyle.danger,
        "LINK": discord.ButtonStyle.link,
    }[style]


class DiscordPyMessageSender:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def _get_channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise DiscordSendError(f"channel {channel_id} is not messageable")
        return channel

    async def send(
        self,
        *,
        channel_id: int,
        message: MessageModel,
        allowed_mentions: CompiledAllowedMentions,
        nonce: str,
    ) -> DiscordSendOutcome:
        channel = await self._get_channel(channel_id)
        embeds = [_build_discord_embed(e) for e in message.embeds]
        view = _build_discord_views(message.action_rows)
        send_kwargs: dict[str, Any] = {
            "content": message.content or None,
            "allowed_mentions": _build_discord_allowed_mentions(allowed_mentions),
            "nonce": nonce,
        }
        if embeds:
            send_kwargs["embeds"] = embeds
        if view is not None:
            send_kwargs["view"] = view
        sent = await channel.send(**send_kwargs)
        return DiscordSendOutcome(discord_message_id=sent.id)

    async def edit(self, *, channel_id: int, message_id: int, payload: EditPayload) -> None:
        channel = await self._get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        kwargs = payload.to_discord_kwargs()
        allowed_mentions_payload = kwargs.pop("allowed_mentions")
        assert isinstance(allowed_mentions_payload, dict)
        edit_kwargs: dict[str, Any] = dict(kwargs)
        edit_kwargs["allowed_mentions"] = discord.AllowedMentions(
            everyone="everyone" in allowed_mentions_payload.get("parse", []),
            users=allowed_mentions_payload.get("users", False) or False,
            roles=allowed_mentions_payload.get("roles", False) or False,
            replied_user=bool(allowed_mentions_payload.get("replied_user", False)),
        )
        await message.edit(**edit_kwargs)

    async def delete(self, *, channel_id: int, message_id: int) -> None:
        channel = await self._get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.delete()
