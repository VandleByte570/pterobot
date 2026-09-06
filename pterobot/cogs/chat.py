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
    """LLM Chat integration cog with server control panel"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.context_manager = ContextManager()
        self.settings = PterobotSettings()
        self.llm_channel_id: Optional[int] = None
    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f'✅ ChatCog loaded - ready for messages')
    
    # ==================== SETUP COMMANDS ====================
    
    @commands.command(name='setupapi')
    @commands.has_permissions(administrator=True)
    async def setup_api(self, ctx: commands.Context):
        """Setup LLM API configuration (admin only)"""
        embed = discord.Embed(
            title='🔧 LLM API Setup Wizard',
            description='Follow the steps below to configure your LLM API',
            color=discord.Color.blue()
        )
        embed.add_field(
            name='Step 1️⃣: Choose Provider',
            value='React with:\n🔵 for OpenAI\n🟣 for Azure',
            inline=False
        )
        embed.add_field(
            name='Step 2️⃣: Send API Key',
            value='Send your API key in DM',
            inline=False
        )
        embed.add_field(
            name='Step 3️⃣: Choose Model',
            value='Choose: gpt-4, gpt-3.5-turbo, etc.',
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='setapikey')
    async def set_api_key(self, ctx: commands.Context, api_key: str, provider: str = 'openai', model: str = 'gpt-3.5-turbo'):
        """Set your LLM API key and provider
        
        Usage: /setapikey <api-key> [provider] [model]
        Providers: openai, azure
        Models: gpt-4, gpt-3.5-turbo, gpt-4-turbo, etc.
        Example: /setapikey sk-xxx openai gpt-4
        """
        # Store in user config
        self.settings.user_llm_config.set_user_api_key(ctx.author.id, api_key, provider)
        
        # Store model preference
        user_key = str(ctx.author.id)
        config = self.settings.user_llm_config.configs.get(user_key, {})
        config['model'] = model
        config['provider'] = provider
        self.settings.user_llm_config.configs[user_key] = config
        self.settings.user_llm_config._save_configs()
        
        embed = discord.Embed(
            title='✅ API Configuration Saved',
            description=f'**Provider:** {provider.upper()}\n**Model:** {model}',
            color=discord.Color.green()
        )
        embed.add_field(
            name='📝 Note',
            value='Your API key has been stored securely. Never share it!',
            inline=False
        )
        
        try:
            await ctx.author.send(embed=embed)
        except:
            pass
        
        await ctx.send(f'✅ {ctx.author.mention}, check your DMs! Your API configuration has been saved.')
    
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
    
    @commands.command(name='apiinfo')
    async def api_info(self, ctx: commands.Context):
        """Check your current API configuration"""
        user_api_key = self.settings.user_llm_config.get_user_api_key(ctx.author.id)
        user_key = str(ctx.author.id)
        config = self.settings.user_llm_config.configs.get(user_key, {})
        
        if not user_api_key:
            embed = discord.Embed(
                title='❌ No API Key Set',
                description='Use `/setapikey` to configure your API',
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        provider = config.get('provider', 'openai')
        model = config.get('model', 'gpt-3.5-turbo')
        
        embed = discord.Embed(
            title='📊 Your API Configuration',
            color=discord.Color.blue()
        )
        embed.add_field(name='Provider', value=provider.upper(), inline=True)
        embed.add_field(name='Model', value=model, inline=True)
        embed.add_field(name='Status', value='✅ Configured', inline=True)
        
        try:
            await ctx.author.send(embed=embed)
        except:
            pass
        
        await ctx.send(f'✅ {ctx.author.mention}, check your DMs for your API info!')
    
    # ==================== CHAT COMMANDS ====================
    
    @commands.command(name='ask')
    async def ask(self, ctx: commands.Context, *, message: str):
        """Ask the AI a question
        
        Usage: /ask <your question>
        Example: /ask What is machine learning?
        """
        # Check if user has API key
        user_api_key = self.settings.user_llm_config.get_user_api_key(ctx.author.id)
        if not user_api_key:
            embed = discord.Embed(
                title='❌ No API Key',
                description='Please configure your API key first:\n`/setapikey <your-key>`',
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
            
            # Get user's model preference
            user_key = str(ctx.author.id)
            config = self.settings.user_llm_config.configs.get(user_key, {})
            provider = config.get('provider', 'openai')
            model = config.get('model', 'gpt-3.5-turbo')
            
            # Create LLM client with user's API key
            llm_client = LLMClient(user_api_key, provider=provider, model=model)
            
            # Get response
            response = await llm_client.chat(
                context.get_messages(),
                temperature=0.7,
                max_tokens=500
            )
            
            if response:
                # Add assistant response to context
                context.add_message('assistant', response)
                
                # Send response with embed
                embed = discord.Embed(
                    title='🤖 AI Response',
                    description=response[:2000],  # Discord has 2000 char limit
                    color=discord.Color.blue()
                )
                embed.set_footer(text=f'Model: {model} | Asked by {ctx.author.name}')
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title='❌ Error',
                    description='Failed to get response from LLM.\n✓ Check your API key\n✓ Check your internet connection\n✓ Try again later',
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
    
    # ==================== SERVER CONTROL PANEL ====================
    
    @commands.command(name='panel')
    @commands.has_permissions(administrator=True)
    async def server_panel(self, ctx: commands.Context):
        """Display the server control panel"""
        embed = discord.Embed(
            title='🎮 Pterodactyl Server Control Panel',
            description='Use the buttons below to manage your game server',
            color=discord.Color.green()
        )
        embed.add_field(
            name='⚙️ Available Actions',
            value='🟢 **Start** - Start the server\n🔴 **Stop** - Stop the server\n🔄 **Restart** - Restart the server\n📊 **Status** - Check server status',
            inline=False
        )
        embed.add_field(
            name='💡 Note',
            value='Only administrators can control the server',
            inline=False
        )
        
        view = ServerControlView()
        await ctx.send(embed=embed, view=view)
    
    @commands.command(name='start')
    @commands.has_permissions(administrator=True)
    async def start_server(self, ctx: commands.Context):
        """Start the game server"""
        embed = discord.Embed(
            title='🟢 Starting Server',
            description='The server is starting...',
            color=discord.Color.green()
        )
        embed.add_field(
            name='⏳ Status',
            value='Starting (please wait 10-30 seconds)',
            inline=False
        )
        await ctx.send(embed=embed)
        # Integration with Pterodactyl API would go here
    
    @commands.command(name='stop')
    @commands.has_permissions(administrator=True)
    async def stop_server(self, ctx: commands.Context):
        """Stop the game server"""
        embed = discord.Embed(
            title='🔴 Stopping Server',
            description='The server is stopping...',
            color=discord.Color.red()
        )
        embed.add_field(
            name='⏳ Status',
            value='Stopping (please wait)',
            inline=False
        )
        await ctx.send(embed=embed)
        # Integration with Pterodactyl API would go here
    
    @commands.command(name='restart')
    @commands.has_permissions(administrator=True)
    async def restart_server(self, ctx: commands.Context):
        """Restart the game server"""
        embed = discord.Embed(
            title='🔄 Restarting Server',
            description='The server is restarting...',
            color=discord.Color.gold()
        )
        embed.add_field(
            name='⏳ Status',
            value='Restarting (please wait)',
            inline=False
        )
        await ctx.send(embed=embed)
        # Integration with Pterodactyl API would go here
    
    @commands.command(name='status')
    async def server_status(self, ctx: commands.Context):
        """Check server status"""
        embed = discord.Embed(
            title='📊 Server Status',
            description='Current server information',
            color=discord.Color.blue()
        )
        embed.add_field(name='State', value='🟢 Online', inline=True)
        embed.add_field(name='Players', value='0/20', inline=True)
        embed.add_field(name='CPU', value='5%', inline=True)
        embed.add_field(name='RAM', value='256MB / 512MB', inline=True)
        await ctx.send(embed=embed)
        # Integration with Pterodactyl API would go here
    
    # ==================== CHAT CHANNEL LISTENER ====================
    
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
                
                # Get user's config
                user_key = str(message.author.id)
                config = self.settings.user_llm_config.configs.get(user_key, {})
                provider = config.get('provider', 'openai')
                model = config.get('model', 'gpt-3.5-turbo')
                
                # Create LLM client
                llm_client = LLMClient(user_api_key, provider=provider, model=model)
                
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

class ServerControlView(discord.ui.View):
    """Buttons for server control panel"""
    
    @discord.ui.button(label='Start', style=discord.ButtonStyle.green, emoji='🟢')
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Only admins can do this!', ephemeral=True)
            return
        
        embed = discord.Embed(
            title='🟢 Starting Server',
            description='The server is starting...',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label='Stop', style=discord.ButtonStyle.red, emoji='🔴')
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Only admins can do this!', ephemeral=True)
            return
        
        embed = discord.Embed(
            title='🔴 Stopping Server',
            description='The server is stopping...',
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label='Restart', style=discord.ButtonStyle.blurple, emoji='🔄')
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Only admins can do this!', ephemeral=True)
            return
        
        embed = discord.Embed(
            title='🔄 Restarting Server',
            description='The server is restarting...',
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label='Status', style=discord.ButtonStyle.blurple, emoji='📊')
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title='📊 Server Status',
            description='Current server information',
            color=discord.Color.blue()
        )
        embed.add_field(name='State', value='🟢 Online', inline=True)
        embed.add_field(name='Players', value='0/20', inline=True)
        embed.add_field(name='CPU', value='5%', inline=True)
        embed.add_field(name='RAM', value='256MB / 512MB', inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """Setup function for loading this cog"""
    await bot.add_cog(ChatCog(bot))
