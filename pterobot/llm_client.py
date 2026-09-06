import aiohttp
import os
from typing import Optional, List, Dict
from datetime import datetime

class ConversationContext:
    """Manage conversation history for users"""
    
    def __init__(self, max_messages: int = 10):
        self.messages: List[Dict] = []
        self.max_messages = max_messages
        self.last_updated = datetime.now()
    
    def add_message(self, role: str, content: str):
        """Add a message to context"""
        self.messages.append({
            'role': role,
            'content': content
        })
        # Keep only recent messages
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        self.last_updated = datetime.now()
    
    def get_messages(self) -> List[Dict]:
        """Get conversation history"""
        return self.messages
    
    def clear(self):
        """Clear conversation history"""
        self.messages = []
        self.last_updated = datetime.now()

class LLMClient:
    """Client for interacting with LLM APIs"""
    
    def __init__(self, api_key: str, provider: str = 'openai', model: str = 'gpt-3.5-turbo'):
        self.api_key = api_key
        self.provider = provider.lower()
        self.model = model
        self.base_url = self._get_base_url()
    
    def _get_base_url(self) -> str:
        """Get API base URL for provider"""
        if self.provider == 'openai':
            return 'https://api.openai.com/v1'
        elif self.provider == 'azure':
            return os.getenv('AZURE_ENDPOINT', '')
        else:
            raise ValueError(f'Unsupported provider: {self.provider}')
    
    async def chat(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 500) -> Optional[str]:
        """Send chat request to LLM"""
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': self.model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f'{self.base_url}/chat/completions',
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        error = await response.text()
                        print(f'LLM API Error: {response.status} - {error}')
                        return None
        except Exception as e:
            print(f'Error calling LLM API: {e}')
            return None

class ContextManager:
    """Manage conversation contexts for multiple users"""
    
    def __init__(self):
        self.contexts: Dict[int, ConversationContext] = {}
    
    def get_context(self, user_id: int) -> ConversationContext:
        """Get or create user context"""
        if user_id not in self.contexts:
            self.contexts[user_id] = ConversationContext()
        return self.contexts[user_id]
    
    def clear_context(self, user_id: int):
        """Clear user's conversation context"""
        if user_id in self.contexts:
            del self.contexts[user_id]
    
    def clear_all(self):
        """Clear all contexts"""
        self.contexts.clear()
