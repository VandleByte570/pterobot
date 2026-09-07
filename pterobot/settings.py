from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class PterobotSettings:
    discord_token: str = os.environ.get("DISCORD_TOKEN", "")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    ptero_base_url: str = os.environ.get("PTERODACTYL_BASE_URL", "").rstrip("/") if os.environ.get("PTERODACTYL_BASE_URL") else ""
    ptero_api_key: str = os.environ.get("PTERODACTYL_API_KEY", "")
    guild_for_dev: Optional[str] = os.environ.get("DEV_GUILD_ID") or None  # optional, speeds slash command registration

    def validate(self):
        if not self.discord_token:
            raise RuntimeError("DISCORD_TOKEN is not set")
        # pterodactyl and openai keys can be optional depending on features used
