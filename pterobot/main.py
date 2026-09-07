import discord

from . import settings

class PteroBot(discord.Client):
    async def on_ready(self):
        print(f'Logged on as {self.user}!')


client = PteroBot()
settings = settings.PterobotSettings()
client.run(settings.token)
