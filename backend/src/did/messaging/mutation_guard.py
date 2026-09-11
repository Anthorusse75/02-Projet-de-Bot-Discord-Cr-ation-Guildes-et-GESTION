"""Safe edit/delete of DID-owned messages (WP5).

An owned-message mutation (edit or delete) is only ever attempted after
verifying, from durable state, that: the delivery actually belongs to the
campaign/owner making the request, it has a real stored Discord message
link, and the destination Guild/channel the caller is targeting matches what
was actually recorded at send time. No caller-supplied guild/channel/message
id is ever trusted on its own for a mutation.
"""

from __future__ import annotations

from did.domain.campaigns import DeliveryStatus, MessageDelivery


class MessageMutationError(ValueError):
    pass


def authorize_owned_message_mutation(
    delivery: MessageDelivery,
    *,
    actor_discord_user_id: int,
    campaign_owner_discord_user_id: int,
    expected_guild_id: int,
    expected_channel_id: int,
) -> int:
    """Return the Discord message id to mutate, or raise.

    Raising means the caller MUST NOT call the Discord adapter at all.
    """
    if actor_discord_user_id != campaign_owner_discord_user_id:
        raise MessageMutationError(
            "only the owning campaign's author may edit or delete its deliveries"
        )
    if delivery.status is not DeliveryStatus.SENT:
        raise MessageMutationError(
            f"delivery is {delivery.status}, not SENT -- no live Discord message to mutate"
        )
    if delivery.discord_message_id is None:
        raise MessageMutationError("delivery has no stored Discord message link")
    if delivery.guild_id != expected_guild_id:
        raise MessageMutationError(
            "destination guild mismatch: refusing to mutate outside the stored guild"
        )
    if delivery.discord_channel_id != expected_channel_id:
        raise MessageMutationError(
            "destination channel mismatch: refusing to mutate outside the stored channel"
        )
    return delivery.discord_message_id
