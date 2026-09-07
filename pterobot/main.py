import asyncio
import logging
import json
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from pterobot import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pterobot")

cfg = settings.PterobotSettings()
cfg.validate()

intents = discord.Intents.default()
intents.message_content = True  # required to read normal messages if you want to use non-slash chat triggers
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix kept for legacy if needed

# ----- LLM call (OpenAI Chat Completion example) -----
async def call_openai(api_key: str, model: str, prompt: str) -> dict:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 800,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"LLM API error {resp.status}: {text}")
            return json.loads(text)

# ----- Pterodactyl API helpers -----
def ptero_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

async def ptero_get(base_url: str, api_key: str, path: str) -> dict:
    url = f"{base_url}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=ptero_headers(api_key), timeout=30) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Pterodactyl GET {url} returned {resp.status}: {text}")
            return json.loads(text)

async def ptero_post(base_url: str, api_key: str, path: str, json_payload: dict) -> dict:
    url = f"{base_url}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=ptero_headers(api_key), json=json_payload, timeout=30) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Pterodactyl POST {url} returned {resp.status}: {text}")
            # Many power endpoints return 204: no content
            if text:
                return json.loads(text)
            return {}

# ----- Slash commands (app commands) -----
class PteroCommands(app_commands.Group):
    pass

ptero_group = PteroCommands(name="ptero", description="Pterodactyl panel/server commands")

@ptero_group.command(name="panel", description="Show configured Pterodactyl panel URL")
async def panel(interaction: discord.Interaction):
    await interaction.response.defer()
    url = cfg.ptero_base_url or "Not configured"
    await interaction.followup.send(f"Pterodactyl panel: {url}")

@ptero_group.command(name="servers", description="List your Pterodactyl servers (requires PTERODACTYL_API_KEY)")
async def servers(interaction: discord.Interaction):
    await interaction.response.defer()
    if not cfg.ptero_api_key or not cfg.ptero_base_url:
        await interaction.followup.send("Pterodactyl base URL or API key is not configured.")
        return
    try:
        # Try common servers endpoint
        srv = await ptero_get(cfg.ptero_base_url, cfg.ptero_api_key, "/api/client/servers")
        servers = srv.get("data", [])
    except Exception as e:
        await interaction.followup.send(f"Failed to fetch servers: {e}")
        return

    if not servers:
        await interaction.followup.send("No servers returned from the panel.")
        return

    lines = []
    for s in servers:
        d = s.get("attributes", {})
        name = d.get("name")
        identifier = d.get("identifier") or d.get("uuid")
        status = d.get("status") or d.get("current_state", "unknown")
        lines.append(f"- {name} (identifier: `{identifier}`) status: {status}")
    await interaction.followup.send("Servers:\n" + "\n".join(lines))

@ptero_group.command(name="start", description="Start a server by identifier")
@app_commands.describe(identifier="Server identifier (not numeric id) from /ptero servers listing")
async def start_server(interaction: discord.Interaction, identifier: str):
    await interaction.response.defer()
    if not cfg.ptero_api_key or not cfg.ptero_base_url:
        await interaction.followup.send("Pterodactyl base URL or API key is not configured.")
        return
    try:
        path = f"/api/client/servers/{identifier}/power"
        await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": "start"})
        await interaction.followup.send(f"Start signal sent to server `{identifier}`.")
    except Exception as e:
        await interaction.followup.send(f"Failed to start server: {e}")

@ptero_group.command(name="stop", description="Stop a server by identifier")
@app_commands.describe(identifier="Server identifier (not numeric id) from /ptero servers listing")
async def stop_server(interaction: discord.Interaction, identifier: str):
    await interaction.response.defer()
    if not cfg.ptero_api_key or not cfg.ptero_base_url:
        await interaction.followup.send("Pterodactyl base URL or API key is not configured.")
        return
    try:
        path = f"/api/client/servers/{identifier}/power"
        await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": "stop"})
        await interaction.followup.send(f"Stop signal sent to server `{identifier}`.")
    except Exception as e:
        await interaction.followup.send(f"Failed to stop server: {e}")

# Register the ptero group
bot.tree.add_command(ptero_group)

# ----- Conversational message handler -----
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Trigger if DM or bot mentioned
    is_dm = message.guild is None
    mentioned = bot.user in message.mentions

    if not is_dm and not mentioned:
        # Not a conversational message for the bot
        return

    prompt = message.content
    # Remove mention text if present
    if mentioned:
        # handle common mention formats
        mention_str1 = f"<@!{bot.user.id}>"
        mention_str2 = f"<@{bot.user.id}>"
        prompt = prompt.replace(mention_str1, "").replace(mention_str2, "").strip()

    log.info("Chat trigger by user=%s user_id=%s channel=%s message_id=%s",
             message.author, message.author.id, getattr(message.channel, "id", "DM"), message.id)

    # show typing
    async with message.channel.typing():
        try:
            llm_resp = None
            if cfg.openai_api_key:
                resp = await call_openai(cfg.openai_api_key, cfg.openai_model, prompt)
                # Try to pull text
                choice = resp.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content") or choice.get("text")
                llm_resp = content or str(resp)
            else:
                llm_resp = "LLM is not configured on this bot. Set OPENAI_API_KEY to enable chat."
        except Exception as e:
            log.exception("LLM call failed")
            llm_resp = f"LLM call failed: {e}"

        # Reply — preserve thread/channel context
        try:
            reply = await message.channel.send(f"{llm_resp}\n\n(Referenced message id: {message.id})")
            log.info("Replied message id=%s to interaction message id=%s", reply.id, message.id)
        except Exception:
            # fallback DM to user
            await message.author.send(f"{llm_resp}\n\n(Referenced message id: {message.id})")

# ----- Ready and command sync -----
@bot.event
async def on_ready():
    log.info("Bot ready: %s (id=%s)", bot.user, bot.user.id)
    # Sync commands: if DEV_GUILD_ID is provided, sync to that guild (faster)
    try:
        if cfg.guild_for_dev:
            log.info("Syncing commands to guild %s", cfg.guild_for_dev)
            guild = discord.Object(id=int(cfg.guild_for_dev))
            await bot.tree.sync(guild=guild)
        else:
            log.info("Syncing global commands (may take up to 1 hour)")
            await bot.tree.sync()
    except Exception as e:
        log.exception("Failed to sync commands: %s", e)


def main():
    bot.run(cfg.discord_token)

if __name__ == "__main__":
    main()
