import os
from pathlib import Path

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class BaseConfig(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
        fb_session_file: str = "session/state.json"
        telegram_bot_token: str = "your_bot_token_here"
        telegram_chat_id: str = "your_chat_id_here"
        scrape_interval_minutes: int = 10
        max_posts_per_group: int = 20
        app_host: str = "0.0.0.0"
        app_port: int = 8000
        app_secret_key: str = "change_this_to_random_string"

except ImportError:
    from pydantic import BaseModel

    # Simple fallback .env loader
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v

    class BaseConfig(BaseModel):
        fb_session_file: str = os.getenv("FB_SESSION_FILE", "session/state.json")
        telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "your_bot_token_here")
        telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "your_chat_id_here")
        scrape_interval_minutes: int = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "10"))
        max_posts_per_group: int = int(os.getenv("MAX_POSTS_PER_GROUP", "20"))
        app_host: str = os.getenv("APP_HOST", "0.0.0.0")
        app_port: int = int(os.getenv("APP_PORT", "8000"))
        app_secret_key: str = os.getenv("APP_SECRET_KEY", "change_this_to_random_string")


class Settings(BaseConfig):
    @property
    def FB_SESSION_FILE(self) -> str:
        return self.fb_session_file

    @property
    def TELEGRAM_BOT_TOKEN(self) -> str:
        return self.telegram_bot_token

    @property
    def TELEGRAM_CHAT_ID(self) -> str:
        return self.telegram_chat_id

    @property
    def SCRAPE_INTERVAL_MINUTES(self) -> int:
        return self.scrape_interval_minutes

    @property
    def MAX_POSTS_PER_GROUP(self) -> int:
        return self.max_posts_per_group

    @property
    def APP_HOST(self) -> str:
        return self.app_host

    @property
    def APP_PORT(self) -> int:
        return self.app_port

    @property
    def APP_SECRET_KEY(self) -> str:
        return self.app_secret_key


settings = Settings()


def get_settings() -> Settings:
    return settings


def get_config() -> Settings:
    return settings
