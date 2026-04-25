import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class for the bot"""
    
    # Bot configuration
    TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    BOT_USERNAME = os.getenv("BOT_USERNAME")
    
    # Directory configuration
    CACHE_DIR = os.getenv("CACHE_DIR", "temp_music")
    LOG_FILE = os.getenv("LOG_FILE", "bot_log.txt")
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.ADMIN_ID:
            raise ValueError("ADMIN_ID is required")
        if not cls.BOT_USERNAME:
            raise ValueError("BOT_USERNAME is required")
        return True
