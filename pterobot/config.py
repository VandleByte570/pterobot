import os
import json
from typing import Optional, Dict

class LLMConfig:
    """Configuration for LLM integration"""
    
    def __init__(self):
        self.api_key: Optional[str] = os.getenv('LLM_API_KEY')
        self.api_provider: str = os.getenv('LLM_PROVIDER', 'openai')
        self.model: str = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
        self.temperature: float = float(os.getenv('LLM_TEMPERATURE', '0.7'))
        self.max_tokens: int = int(os.getenv('LLM_MAX_TOKENS', '500'))
        
    def is_configured(self) -> bool:
        """Check if LLM is properly configured"""
        return self.api_key is not None and len(self.api_key) > 0

class UserLLMConfig:
    """Per-user LLM configuration storage"""
    
    def __init__(self, config_file: str = 'user_llm_config.json'):
        self.config_file = config_file
        self.configs: Dict[str, Dict] = self._load_configs()
    
    def _load_configs(self) -> Dict:
        """Load user configs from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_configs(self):
        """Save user configs to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.configs, f, indent=2)
    
    def set_user_api_key(self, user_id: int, api_key: str, provider: str = 'openai'):
        """Store user's API key"""
        user_key = str(user_id)
        self.configs[user_key] = {
            'api_key': api_key,
            'provider': provider
        }
        self._save_configs()
    
    def get_user_api_key(self, user_id: int) -> Optional[str]:
        """Get user's API key"""
        user_key = str(user_id)
        if user_key in self.configs:
            return self.configs[user_key].get('api_key')
        return None
    
    def remove_user_api_key(self, user_id: int):
        """Remove user's API key"""
        user_key = str(user_id)
        if user_key in self.configs:
            del self.configs[user_key]
            self._save_configs()

class PterobotSettings:
    """Main bot settings"""
    token: str = ''
    llm_config: Optional[LLMConfig] = None
    user_llm_config: Optional[UserLLMConfig] = None
    
    def __init__(self):
        self.token = os.getenv('DISCORD_TOKEN', '')
        self.llm_config = LLMConfig()
        self.user_llm_config = UserLLMConfig()
