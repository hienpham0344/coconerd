"""Sequential durable delivery, woken by WebSocket or a fallback timer."""

import asyncio
from contextlib import suppress

import discord

try:
    from bot.action_events import listen_action_events, wait_for_actions
    from bot.delivery import DeliveryError, DeliveryReceipts, TopicDelivery
except ImportError:
    from action_events import listen_action_events, wait_for_actions
    from delivery import DeliveryError, DeliveryReceipts, TopicDelivery


async def process_outbox_actions(bot) -> None:
    await bot.wait_until_ready()
    wakeup = bot._action_wakeup
    watcher = asyncio.create_task(listen_action_events(bot.backend, wakeup))
    delivery = TopicDelivery(bot, bot.backend, DeliveryReceipts(bot.backend))
    try:
        while not bot.is_closed():
            # Clear before the claim: hints arriving during claim/delivery stay set.
            wakeup.clear()
            actions = []
            try:
                actions = await bot.backend.claim_actions(bot.worker_id, limit=1)
                for action in actions:
                    action_id = action["action_id"]
                    try:
                        result = await delivery.deliver(action)
                        completed = await bot.backend.complete_action(
                            action_id, bot.worker_id, **result
                        )
                        if completed:
                            target = result.get("discord_thread_id")
                            print(
                                f"✅ [ACTION] {action['type']} completed"
                                + (f" in Thread {target}" if target else "")
                            )
                        else:
                            print(f"⚠️ [ACTION] ACK rejected for {action_id}; receipts retained")
                    except Exception as exc:
                        retryable = (
                            exc.retryable
                            if isinstance(exc, DeliveryError)
                            else not isinstance(exc, (discord.Forbidden, discord.NotFound))
                        )
                        print(f"⚠️ [ACTION] {action_id}: {type(exc).__name__}")
                        await bot.backend.fail_action(
                            action_id,
                            bot.worker_id,
                            type(exc).__name__,
                            str(exc),
                            retryable=retryable,
                        )
            except Exception as exc:
                actions = []
                print(f"⚠️ [OUTBOX] {type(exc).__name__}")
            if not actions and not bot.is_closed():
                await wait_for_actions(wakeup)
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
