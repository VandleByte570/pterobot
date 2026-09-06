import discord
from discord.ext import commands
from typing import Optional
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_client import LLMClient, ContextManager, ConversationContext
from config import PterobotSettings

class ChatCog(commands.Cog):
    """LLM Chat integration cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.context_manager = ContextManager()
        self.settings = PterobotSettings()
        self.llm_channel_id: Optional[int] = None
    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f'ChatCog loaded - ready for messages')
    
    @commands.command(name='setchatchannel')
    @commands.has_permissions(administrator=True)
    async def set_chat_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for LLM chat (admin only)"""
        self.llm_channel_id = channel.id
        embed = discord.Embed(
            title='✅ Chat Channel Set',
            description=f'LLM chat channel set to {channel.mention}',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    
    @commands.command(name='setapikey')
    async def set_api_key(self, ctx: commands.Context, api_key: str, provider: str = 'openai'):
        """Set your LLM API key (stored securely in DM)"""
        # Store in user config
        self.settings.user_llm_config.set_user_api_key(ctx.author.id, api_key, provider)
        
        embed = discord.Embed(
            title='✅ API Key Stored',
            description=f'Your {provider.upper()} API key has been stored securely.',
            color=discord.Color.green()
        )
        await ctx.author.send(embed=embed)
        
        # Confirm in channel
        await ctx.send(f'{ctx.author.mention}, check your DMs! Your API key has been stored.')
    
    @commands.command(name='removetoken')
    async def remove_api_key(self, ctx: commands.Context):
        """Remove your stored API key"""
        self.settings.user_llm_config.remove_user_api_key(ctx.author.id)
        
        embed = discord.Embed(
            title='✅ API Key Removed',
            description='Your API key has been removed from storage.',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    
    @commands.command(name='chat')
    async def chat_command(self, ctx: commands.Context, *, message: str):
        """Send a message to the LLM"""
        # Check if user has API key
        user_api_key = self.settings.user_llm_config.get_user_api_key(ctx.author.id)
        if not user_api_key:
            embed = discord.Embed(
                title='❌ No API Key',
                description='Please set your API key first using `/setapikey <your-key>`',
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        # Show typing indicator
        async with ctx.typing():
            # Get or create context
            context = self.context_manager.get_context(ctx.author.id)
            
            # Add user message to context
            context.add_message('user', message)
            
            # Create LLM client with user's API key
            llm_client = LLMClient(user_api_key, provider='openai')
            
            # Get response
            response = await llm_client.chat(
                context.get_messages(),
                temperature=0.7,
                max_tokens=500
            )
            
            if response:
                # Add assistant response to context
                context.add_message('assistant', response)
                
                # Send response
                embed = discord.Embed(
                    title='🤖 AI Response',
                    description=response[:2000],  # Discord has 2000 char limit
                    color=discord.Color.blue()
                )
                embed.set_footer(text=f'Requested by {ctx.author.name}')
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title='❌ Error',
                    description='Failed to get response from LLM. Check your API key or try again.',
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
    
    @commands.command(name='clearchathistory')
    async def clear_history(self, ctx: commands.Context):
        """Clear your conversation history"""
        self.context_manager.clear_context(ctx.author.id)
        
        embed = discord.Embed(
            title='✅ History Cleared',
            description='Your conversation history has been cleared.',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages in the chat channel"""
        if message.author == self.bot.user:
            return
        
        if self.llm_channel_id and message.channel.id == self.llm_channel_id:
            # Check if user has API key
            user_api_key = self.settings.user_llm_config.get_user_api_key(message.author.id)
            if not user_api_key:
                embed = discord.Embed(
                    title='❌ No API Key',
                    description='Please set your API key first using `/setapikey <your-key>`',
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed)
                return
            
            # Show typing indicator
            async with message.channel.typing():
                # Get or create context
                context = self.context_manager.get_context(message.author.id)
                
                # Add user message
                context.add_message('user', message.content)
                
                # Create LLM client
                llm_client = LLMClient(user_api_key, provider='openai')
                
                # Get response
                response = await llm_client.chat(
                    context.get_messages(),
                    temperature=0.7,
                    max_tokens=500
                )
                
                if response:
                    # Add to context
                    context.add_message('assistant', response)
                    
                    # Send response
                    embed = discord.Embed(
                        title='🤖 AI Response',
                        description=response[:2000],
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text=f'Replying to {message.author.name}')
                    await message.channel.send(embed=embed)

async def setup(bot: commands.Bot):
    """Setup function for loading this cog"""
    await bot.add_cog(ChatCog(bot))
