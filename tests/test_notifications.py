"""Discord embeds and routing are inspected without constructing live webhooks."""
from unittest.mock import Mock

import pytest

import discord_handler


@pytest.fixture
def webhook_factory(monkeypatch):
    webhooks = []

    def from_url(url):
        webhook = Mock()
        webhook.url = url
        webhooks.append(webhook)
        return webhook

    monkeypatch.setattr(discord_handler.discord.SyncWebhook, "from_url", from_url)
    return webhooks


def test_multiple_webhooks_receive_message_and_optional_thread(webhook_factory):
    handler = discord_handler.DiscordWebhookHandler(" https://example.invalid/one, , https://example.invalid/two?thread_id=123 ")
    handler.send_message("synthetic update")
    assert len(webhook_factory) == 2
    for webhook in webhook_factory:
        assert webhook.send.call_args.args == ("synthetic update",)
    assert "thread" not in webhook_factory[0].send.call_args.kwargs
    assert webhook_factory[1].send.call_args.kwargs["thread"].id == 123


def test_empty_webhook_list_performs_no_delivery(webhook_factory):
    handler = discord_handler.DiscordWebhookHandler(" , ")
    handler.send_message("unused")
    assert webhook_factory == []


def test_optional_user_ping_and_missing_user_validation(webhook_factory):
    handler = discord_handler.DiscordWebhookHandler("https://example.invalid/test", "123456789012345678")
    handler.send_message("arriving", ping=True)
    assert webhook_factory[0].send.call_args.args[0] == "<@123456789012345678> arriving"
    handler.userID = ""
    webhook_factory[0].send.reset_mock()
    with pytest.raises(handler.UserIDNotSetError):
        handler.send_message("arriving", ping=True)
    webhook_factory[0].send.assert_not_called()


@pytest.mark.parametrize("ping", [False, True])
def test_rich_embed_preserves_content_image_and_ping(webhook_factory, ping):
    handler = discord_handler.DiscordWebhookHandler("https://example.invalid/test?thread_id=123", "42")
    handler.send_message_with_embed("Carrier ABC-123", "Cargo is ready", "https://example.invalid/image.png", ping=ping)
    call = webhook_factory[0].send.call_args
    embed = call.kwargs["embed"].to_dict()
    assert embed["title"] == "Carrier ABC-123"
    assert embed["description"] == "Cargo is ready"
    assert embed["image"]["url"] == "https://example.invalid/image.png"
    assert call.args == (("<@42>",) if ping else ())
    assert call.kwargs["thread"].id == 123


@pytest.mark.parametrize("status,expected_location", [
    ("jump_plotted", "Sol"), ("jump_completed", "Achenar"),
    ("jump_cancelled", "Sol"), ("cooldown_finished", "Sol"),
])
def test_jump_embed_has_identity_time_location_and_status_color(webhook_factory, status, expected_location):
    handler = discord_handler.DiscordWebhookHandler("https://example.invalid/test")
    handler.send_jump_status_embed(status, "Test Carrier", "ABC-123", "Sol", "Earth", "Achenar", "Achenar 1", "<t:1000:R>")
    embed = webhook_factory[0].send.call_args.kwargs["embed"].to_dict()
    assert "Test Carrier" in embed["title"] and "ABC-123" in embed["title"]
    assert "<t:1000:R>" in embed["description"]
    assert expected_location in embed["fields"][0]["value"]
    assert isinstance(embed["color"], int) and embed["color"] > 0


@pytest.mark.known_defect("NOTIFY-001")
@pytest.mark.parametrize("status", ["jump_plotted", "jump_completed"])
def test_missing_location_has_meaningful_placeholder_in_description(webhook_factory, status):
    handler = discord_handler.DiscordWebhookHandler("https://example.invalid/test")
    handler.send_jump_status_embed(status, "Test Carrier", "ABC-123", None, None, None, None, None)
    embed = webhook_factory[0].send.call_args.kwargs["embed"].to_dict()
    assert "None" not in embed["description"]
    assert "Unknown" in embed["description"]


def test_delivery_failure_is_visible_to_caller(webhook_factory):
    handler = discord_handler.DiscordWebhookHandler("https://example.invalid/test")
    webhook_factory[0].send.side_effect = RuntimeError("synthetic delivery failure")
    with pytest.raises(RuntimeError):
        handler.send_message("update")
