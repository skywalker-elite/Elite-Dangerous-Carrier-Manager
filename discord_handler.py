from typing import Literal
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
        if ping:
            message = self._get_ping_message() + " " + message
        webhook.send(message, username=self.username, avatar_url=self.avatar_url)

    def _send_embed(self, embed: discord.Embed, ping: bool = False):
        webhook = discord.SyncWebhook.from_url(self.webhook_url)
        if ping:
            webhook.send(self._get_ping_message(), embed=embed, username=self.username, avatar_url=self.avatar_url)
        else:
            webhook.send(embed=embed, username=self.username, avatar_url=self.avatar_url)

    def send_message_with_embed(self, title: str, description: str, image_url: str|None=None, ping: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
        )
        if image_url:
            embed.set_image(url=image_url)
        self._send_embed(embed, ping=ping)

    def _get_ping_message(self):
        if self.userID != '':
            return f'<@{self.userID}>'
        else:
            raise self.UserIDNotSetError("User ID is not set")

    def send_jump_status_embed(self, status: Literal['jump_plotted', 'jump_completed', 'jump_cancelled', 'cooldown_finished'], 
                                name: str, callsign: str, current_system: str, current_body: str,
                                other_system: str|None, other_body: str|None, timestamp: str|None, ping: bool = False) -> None:
        
        color_map = {
            'jump_plotted': 4218367,
            'jump_completed': 11055871,
            'jump_cancelled': 16730955,
            'cooldown_finished': 5239664,
        }
        description_map = {
            'jump_plotted': f"Jump plotted to **{other_system}** body **{other_body}**, arriving {timestamp}",
            'jump_completed': f"Jump completed at **{current_system}** body **{current_body}**, cooldown finishes {timestamp}",
            'jump_cancelled': f"Jump cancelled, cooldown finishes {timestamp}",
            'cooldown_finished': "Cooldown complete, ready to jump",
        }

        embed = discord.Embed(
            color=color_map[status],
            title=f"{name} ({callsign})",
            description=description_map[status],
        ).add_field(
            name="Current Location" if status != 'jump_completed' else "Previous Location",
            value=f"**{current_system if status != 'jump_completed' else other_system}** body **{current_body if status != 'jump_completed' else other_body}**",
            inline=True,
        )

        self._send_embed(embed, ping=ping)

if __name__ == "__main__":
    from datetime import datetime, timezone, timedelta
    settings = Settings(getSettingsPath())
    settings.load()
    webhook_handler = DiscordWebhookHandler(settings.get('discord', 'webhook'), settings.get('discord', 'userID'))
    # webhook_handler.send_message_with_embed("P.T.N. Carrier (PTN-123)", f"Jump plotted to **Sol** body **Earth**, arriving <t:{(datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp():.0f}:R>", ping=True)
    webhook_handler.send_jump_status_embed(
        status='jump_plotted', name='P.T.N. Carrier', callsign='PTN-123', 
        current_system='Alpha Centauri', current_body='Proxima Centauri B',
        other_system='Sol', other_body='Earth', timestamp=f'<t:{(datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp():.0f}:R>', ping=False
    )
    webhook_handler.send_jump_status_embed(
        status='jump_completed', name='P.T.N. Carrier', callsign='PTN-123', 
        current_system='Sol', current_body='Earth',
        other_system='Alpha Centauri', other_body='Proxima Centauri B', timestamp=f'<t:{(datetime.now(timezone.utc) + timedelta(minutes=20)).timestamp():.0f}:R>', ping=False
    )
    webhook_handler.send_jump_status_embed(
        status='cooldown_finished', name='P.T.N. Carrier', callsign='PTN-123', 
        current_system='Sol', current_body='Earth', other_system=None, other_body=None, timestamp=None, ping=True
    )
    webhook_handler.send_jump_status_embed(
        status='jump_cancelled', name='P.T.N. Carrier', callsign='PTN-123', 
        current_system='Sol', current_body='Earth', other_system=None, other_body=None, timestamp=f'<t:{(datetime.now(timezone.utc) + timedelta(minutes=25)).timestamp():.0f}:R>', ping=False
    )