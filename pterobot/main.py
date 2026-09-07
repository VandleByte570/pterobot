import asyncio
import logging
import json
import os
import time
from typing import Optional, List, Dict

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

# In-memory cooldown trackers
_last_user_action: Dict[int, float] = {}
_last_server_action: Dict[str, float] = {}

AUDIT_LOG_PATH = os.environ.get("PTEROBOT_AUDIT_LOG", "pterobot/audit.log")

# ----- utility helpers -----
def audit_entry(entry: dict):
    try:
        dirpath = os.path.dirname(AUDIT_LOG_PATH)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        log.exception("Failed to write audit log")


def can_control(member: discord.Member) -> bool:
    # Allow guild admins / manage_guild
    try:
        if member.guild is None:
            return False
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        # Check configured admin user ids
        if getattr(cfg, "admin_user_ids", None):
            if member.id in cfg.admin_user_ids:
                return True
        # Check configured roles
        if getattr(cfg, "control_role_ids", None):
            member_role_ids = [r.id for r in member.roles]
            for rid in cfg.control_role_ids:
                if rid in member_role_ids:
                    return True
    except Exception:
        log.exception("Error checking permissions for member %s", member)
    return False


def is_on_cooldown_user(user_id: int) -> Optional[float]:
    last = _last_user_action.get(user_id)
    if not last:
        return None
    elapsed = time.time() - last
    if elapsed < cfg.power_cooldown_seconds:
        return cfg.power_cooldown_seconds - elapsed
    return None


def is_on_cooldown_server(identifier: str) -> Optional[float]:
    last = _last_server_action.get(identifier)
    if not last:
        return None
    elapsed = time.time() - last
    if elapsed < cfg.power_cooldown_seconds:
        return cfg.power_cooldown_seconds - elapsed
    return None


def mark_action(user_id: int, identifier: str):
    _last_user_action[user_id] = time.time()
    _last_server_action[identifier] = time.time()

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
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"__raw_text": text}

async def ptero_post(base_url: str, api_key: str, path: str, json_payload: dict) -> dict:
    url = f"{base_url}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=ptero_headers(api_key), json=json_payload, timeout=30) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Pterodactyl POST {url} returned {resp.status}: {text}")
            # Many power endpoints return 204: no content
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"__raw_text": text}
            return {}

# ----- UI components for interactive controls -----
class ActionButton(discord.ui.Button):
    def __init__(self, label: str, action: str, identifier: str):
        # choose style based on action
        style = discord.ButtonStyle.primary if action == "start" else discord.ButtonStyle.danger
        super().__init__(label=label, style=style)
        self.action = action  # e.g., 'start', 'stop', 'restart'
        self.identifier = identifier

    async def callback(self, interaction: discord.Interaction):
        # check permission quick path
        member = interaction.user
        if not isinstance(member, discord.Member):
            # try to fetch member if possible
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except Exception:
                member = interaction.user
        if not can_control(member):
            await interaction.response.send_message("You don't have permission to control servers.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": self.identifier,
                "result": "denied",
                "details": "permission",
            })
            return

        # Ask for a confirmation via an ephemeral message with Confirm/Cancel
        view = ConfirmView(self.action, self.identifier)
        await interaction.response.send_message(
            f"Are you sure you want to **{self.action}** server `{self.identifier}`?",
            ephemeral=True,
            view=view,
        )


class ConfirmButton(discord.ui.Button):
    def __init__(self, action: str, identifier: str):
        super().__init__(label="Confirm", style=discord.ButtonStyle.danger)
        self.action = action
        self.identifier = identifier

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        identifier = self.identifier

        # Permission re-check
        member = interaction.user
        if interaction.guild and not isinstance(member, discord.Member):
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except Exception:
                member = interaction.user
        if not can_control(member):
            await interaction.followup.send("You don't have permission to perform this action.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": identifier,
                "result": "denied",
                "details": "permission",
            })
            return

        # Cooldown checks
        user_cd = is_on_cooldown_user(user_id)
        if user_cd:
            await interaction.followup.send(f"You're on cooldown for {int(user_cd)}s before next power action.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": identifier,
                "result": "denied",
                "details": "cooldown_user",
            })
            return
        srv_cd = is_on_cooldown_server(identifier)
        if srv_cd:
            await interaction.followup.send(f"Server `{identifier}` is on cooldown for {int(srv_cd)}s.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": identifier,
                "result": "denied",
                "details": "cooldown_server",
            })
            return

        # Perform API call
        try:
            path = f"/api/client/servers/{identifier}/power"
            # retry once on 5xx
            try:
                await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": self.action})
                result = "success"
                details = "ok"
            except RuntimeError as e:
                # if 5xx maybe retry once
                log.exception("First power call failed, attempting retry")
                await asyncio.sleep(1)
                await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": self.action})
                result = "success"
                details = "ok_after_retry"

            # mark cooldowns
            mark_action(user_id, identifier)
            await interaction.followup.send(f"Server `{identifier}` {self.action} signal sent.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": identifier,
                "result": result,
                "details": details,
            })
        except Exception as e:
            log.exception("Failed to send power signal")
            await interaction.followup.send(f"Failed to {self.action} server `{identifier}`: {e}", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": self.action,
                "server": identifier,
                "result": "error",
                "details": str(e),
            })


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Action cancelled.", ephemeral=True)


class ConfirmView(discord.ui.View):
    def __init__(self, action: str, identifier: str):
        super().__init__(timeout=60)
        self.add_item(ConfirmButton(action, identifier))
        self.add_item(CancelButton())


class ServerActionView(discord.ui.View):
    def __init__(self, identifier: str):
        super().__init__(timeout=300)
        # Add action buttons for start/stop/restart
        self.add_item(ActionButton("Start", "start", identifier))
        self.add_item(ActionButton("Stop", "stop", identifier))
        self.add_item(ActionButton("Restart", "restart", identifier))


class ServerSelect(discord.ui.Select):
    def __init__(self, servers: List[dict]):
        options = []
        # Limit to 25 options (discord max)
        for s in servers[:25]:
            d = s.get("attributes", {})
            name = d.get("name", "Unknown")
            identifier = d.get("identifier") or d.get("uuid") or "unknown"
            label = f"{name}"
            options.append(discord.SelectOption(label=label[:100], value=identifier))
        super().__init__(placeholder="Select a server to control", min_values=1, max_values=1, options=options)
        self.servers = servers

    async def callback(self, interaction: discord.Interaction):
        identifier = self.values[0]
        # find server metadata
        chosen = None
        for s in self.servers:
            d = s.get("attributes", {})
            id_ = d.get("identifier") or d.get("uuid")
            if id_ == identifier:
                chosen = d
                break
        name = chosen.get("name") if chosen else identifier
        status = chosen.get("status") or chosen.get("current_state", "unknown") if chosen else "unknown"
        embed = discord.Embed(
            title=f"Server: {name}",
            description=f"Identifier: `{identifier}`\nStatus: **{status}**",
            color=0x2ECC71 if status == "running" else 0xE67E22 if status in ("starting", "stopping") else 0x95A5A6,
        )
        # Provide quick links if possible
        if cfg.ptero_base_url:
            server_url = f"{cfg.ptero_base_url}/server/{identifier}"
            embed.add_field(name="Panel link", value=f"[Open Server]({server_url})", inline=False)
        # Send ephemeral embed with action buttons
        view = ServerActionView(identifier)
        # Check permission: if user cannot control, show message instead of action buttons
        member = interaction.user
        if interaction.guild and not isinstance(member, discord.Member):
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except Exception:
                member = interaction.user
        if not can_control(member):
            await interaction.response.send_message("You don't have permission to control servers.", ephemeral=True)
            audit_entry({
                "ts": time.time(),
                "user_id": interaction.user.id,
                "user": str(interaction.user),
                "action": "view_server",
                "server": identifier,
                "result": "denied",
                "details": "permission",
            })
            return

        await interaction.response.send_message(embed=embed, ephemeral=True, view=view)


class ServerSelectView(discord.ui.View):
    def __init__(self, servers: List[dict]):
        super().__init__(timeout=300)
        self.add_item(ServerSelect(servers))


# ----- Slash commands (app commands) -----
class PteroCommands(app_commands.Group):
    pass

ptero_group = PteroCommands(name="ptero", description="Pterodactyl panel/server commands")

@ptero_group.command(name="panel", description="Show a rich Pterodactyl panel embed with interactive controls")
async def panel(interaction: discord.Interaction):
    """Show a rich embed linking to the Pterodactyl panel and summary of servers with interactive controls."""
    await interaction.response.defer()
    url = cfg.ptero_base_url or None
    if not url:
        embed = discord.Embed(
            title="Pterodactyl Panel",
            description="Panel URL is not configured. Please set PTERODACTYL_BASE_URL in the bot configuration.",
            color=0xE74C3C,
        )
        await interaction.followup.send(embed=embed)
        return

    # Build the base embed
    embed = discord.Embed(
        title="Pterodactyl Panel",
        description="Manage your game servers from the Pterodactyl web panel. Use the selector below to pick a server and run Start/Stop/Restart.",
        color=0x7289DA,
        url=url,
    )
    # Optional thumbnail - replace with your logo URL if you have one
    embed.set_thumbnail(url="https://raw.githubusercontent.com/iamkubi/pterobot/main/logo.png")
    embed.add_field(name="Panel URL", value=f"[Open Panel]({url})", inline=False)

    servers = []
    server_lines: List[str] = []
    try:
        if cfg.ptero_api_key:
            srv = await ptero_get(cfg.ptero_base_url, cfg.ptero_api_key, "/api/client/servers")
            servers = srv.get("data", [])
            if not servers:
                server_lines.append("No servers found on the panel.")
            else:
                for s in servers[:8]:  # show up to 8 servers
                    d = s.get("attributes", {})
                    name = d.get("name", "Unknown")
                    identifier = d.get("identifier") or d.get("uuid") or "unknown"
                    status = d.get("status") or d.get("current_state", "unknown")
                    server_url = f"{url}/server/{identifier}" if identifier and identifier != "unknown" else url
                    server_lines.append(f"**{name}** — {status} — [Open]({server_url})")
        else:
            server_lines.append("Pterodactyl API key not configured; set PTERODACTYL_API_KEY to show servers and enable controls.")
    except Exception as e:
        log.exception("Failed to fetch servers for panel embed")
        server_lines.append(f"Failed to fetch servers: {e}")

    if server_lines:
        embed.add_field(name="Servers", value="\n".join(server_lines), inline=False)

    embed.set_footer(text="PteroBot — Control your servers from the panel")

    # Main view: open panel button + (if servers) selector to pick a server for controls
    main_view = discord.ui.View()
    main_view.add_item(discord.ui.Button(label="Open Panel", style=discord.ButtonStyle.url, url=url))

    if servers:
        # add a server select component (ephemeral controls will be shown after selection)
        main_view.add_item(ServerSelect(servers))

    await interaction.followup.send(embed=embed, view=main_view)


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
    # permission check
    member = interaction.user
    if interaction.guild and not isinstance(member, discord.Member):
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except Exception:
            member = interaction.user
    if not can_control(member):
        await interaction.followup.send("You don't have permission to control servers.")
        return
    try:
        path = f"/api/client/servers/{identifier}/power"
        await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": "start"})
        await interaction.followup.send(f"Start signal sent to server `{identifier}`.")
        audit_entry({
            "ts": time.time(),
            "user_id": interaction.user.id,
            "user": str(interaction.user),
            "action": "start",
            "server": identifier,
            "result": "success",
            "details": "via slash",
        })
        mark_action(interaction.user.id, identifier)
    except Exception as e:
        await interaction.followup.send(f"Failed to start server: {e}")
        audit_entry({
            "ts": time.time(),
            "user_id": interaction.user.id,
            "user": str(interaction.user),
            "action": "start",
            "server": identifier,
            "result": "error",
            "details": str(e),
        })


@ptero_group.command(name="stop", description="Stop a server by identifier")
@app_commands.describe(identifier="Server identifier (not numeric id) from /ptero servers listing")
async def stop_server(interaction: discord.Interaction, identifier: str):
    await interaction.response.defer()
    if not cfg.ptero_api_key or not cfg.ptero_base_url:
        await interaction.followup.send("Pterodactyl base URL or API key is not configured.")
        return
    # permission check
    member = interaction.user
    if interaction.guild and not isinstance(member, discord.Member):
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except Exception:
            member = interaction.user
    if not can_control(member):
        await interaction.followup.send("You don't have permission to control servers.")
        return
    try:
        path = f"/api/client/servers/{identifier}/power"
        await ptero_post(cfg.ptero_base_url, cfg.ptero_api_key, path, {"signal": "stop"})
        await interaction.followup.send(f"Stop signal sent to server `{identifier}`.")
        audit_entry({
            "ts": time.time(),
            "user_id": interaction.user.id,
            "user": str(interaction.user),
            "action": "stop",
            "server": identifier,
            "result": "success",
            "details": "via slash",
        })
        mark_action(interaction.user.id, identifier)
    except Exception as e:
        await interaction.followup.send(f"Failed to stop server: {e}")
        audit_entry({
            "ts": time.time(),
            "user_id": interaction.user.id,
            "user": str(interaction.user),
            "action": "stop",
            "server": identifier,
            "result": "error",
            "details": str(e),
        })


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
