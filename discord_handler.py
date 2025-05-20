import discord
from settings import Settings
from utility import getSettingsPath

class DiscordWebhookHandler:
    class UserIDNotSetError(Exception):
        pass
    def __init__(self, webhook_url: str, userID: str = ''):
        self.webhook_url = webhook_url
        self.userID = userID
        self.username = "Elite Dangerous Carrier Manager"
        self.avatar_url = "https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/blob/main/images/EDCM.png?raw=true"

    def send_message(self, message: str, ping: bool = False):
        webhook = discord.SyncWebhook.from_url(self.webhook_url)
        webhook.send(message, username=self.username, avatar_url=self.avatar_url)
        if ping:
            self.send_ping()

    def send_embed(self, embed: discord.Embed):
        webhook = discord.SyncWebhook.from_url(self.webhook_url)
        webhook.send(embed=embed, username=self.username, avatar_url=self.avatar_url)

    def send_message_with_embed(self, title: str, description: str, ping: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
        )
        self.send_embed(embed)
        if ping:
            self.send_ping()

    def send_ping(self):
        if self.userID != '':
            webhook = discord.SyncWebhook.from_url(self.webhook_url)
            webhook.send(f'<@{self.userID}>', username=self.username, avatar_url=self.avatar_url)
        else:
            raise self.UserIDNotSetError("User ID is not set")

if __name__ == "__main__":
    from datetime import datetime, timezone, timedelta
    settings = Settings(getSettingsPath())
    settings.load()
    webhook_handler = DiscordWebhookHandler(settings.get('discord', 'webhook'), settings.get('discord', 'userID'))
    webhook_handler.send_message_with_embed("P.T.N. Carrier (PTN-123)", f"Jump plotted to **Sol** body **Earth**, arriving <t:{(datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp():.0f}:R>", ping=True)