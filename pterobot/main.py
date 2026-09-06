import discord
from discord.ext import commands
import os
import asyncio
from pathlib import Path

from config import PterobotSettings

# Initialize bot with command prefix
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)

# Load settings
settings = PterobotSettings()

@bot.event
async def on_ready():
    print(f'✅ Logged on as {bot.user}!')
    print(f'📢 Syncing commands...')
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'❌ Failed to sync commands: {e}')

async def load_cogs():
    """Load all cogs from the cogs directory"""
    cogs_dir = Path(__file__).parent / 'cogs'
    
    for cog_file in cogs_dir.glob('*.py'):
        if cog_file.name.startswith('_'):
            continue
        
        cog_name = cog_file.stem
        try:
            await bot.load_extension(f'pterobot.cogs.{cog_name}')
            print(f'✅ Loaded cog: {cog_name}')
        except Exception as e:
            print(f'❌ Failed to load cog {cog_name}: {e}')

async def main():
    """Main bot startup function"""
    async with bot:
        # Load all cogs
        await load_cogs()
        
        # Run the bot
        await bot.start(settings.token)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Bot shutdown by user')
    except Exception as e:
        print(f'❌ Bot error: {e}')
        raise
