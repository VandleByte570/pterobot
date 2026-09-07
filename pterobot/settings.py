from dataclasses import dataclass
from typing import Optional, List
import os

@dataclass
class PterobotSettings:
    discord_token: str = os.environ.get("DISCORD_TOKEN", "")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    ptero_base_url: str = os.environ.get("PTERODACTYL_BASE_URL", "").rstrip("/") if os.environ.get("PTERODACTYL_BASE_URL") else ""
    ptero_api_key: str = os.environ.get("PTERODACTYL_API_KEY", "")
    guild_for_dev: Optional[str] = os.environ.get("DEV_GUILD_ID") or None
    control_role_ids: List[int] = []
    admin_user_ids: List[int] = []
    power_cooldown_seconds: int = 30

    def __post_init__(self):
        # parse control role ids CSV
        roles = os.environ.get("CONTROL_ROLE_ID", "")
        if roles:
            try:
                self.control_role_ids = [int(r.strip()) for r in roles.split(",") if r.strip()]
            except Exception:
                self.control_role_ids = []
        admins = os.environ.get("ADMIN_USER_IDS", "")
        if admins:
            try:
                self.admin_user_ids = [int(u.strip()) for u in admins.split(",") if u.strip()]
            except Exception:
                self.admin_user_ids = []
        try:
            self.power_cooldown_seconds = int(os.environ.get("POWER_COOLDOWN_SECONDS", self.power_cooldown_seconds))
        except Exception:
            self.power_cooldown_seconds = 30

    def validate(self):
        if not self.discord_token:
            raise RuntimeError("DISCORD_TOKEN is not set")
        # pterodactyl and openai keys can be optional depending on features used
