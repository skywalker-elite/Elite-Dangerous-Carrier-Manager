import discord
from settings import Settings
from utility import getSettingsPath

class DiscordWebhookHandler:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.username = "Elite Dangerous Carrier Manager"
        self.avatar_url = "https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/blob/main/images/EDCM.png?raw=true"

    def send_message(self, title: str, description: str):
        embed = discord.Embed(title=title, description=description)
        self.send_embed(embed)

    def send_embed(self, embed: discord.Embed):
        webhook = discord.SyncWebhook.from_url(self.webhook_url)
        webhook.send(embed=embed, username=self.username, avatar_url=self.avatar_url)

    def send_message_with_embed(self, title: str, description: str):
        embed = discord.Embed(
            title=title,
            description=description,
        )
        self.send_embed(embed)

if __name__ == "__main__":
    from datetime import datetime, timezone, timedelta
    from utility import getHammerCountdown
    settings = Settings(getSettingsPath())
    settings.load()
    webhook_handler = DiscordWebhookHandler(settings.get('discord')['discord_webhook'])
    webhook_handler.send_message_with_embed("P.T.N. Carrier (PTN-123)", f"Jump plotted to **Sol** body **Earth**, arriving <t:{(datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp():.0f}:R>")