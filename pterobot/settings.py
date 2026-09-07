import os


class PterobotSettings():
    token = os.getenv('DISCORD_TOKEN', '')
