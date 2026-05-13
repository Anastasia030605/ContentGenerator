"""Конфигурация приложения"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    """Настройки приложения"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram
    telegram_channel_username: str
    # Устаревшие поля (не нужны для веб-парсинга, но оставлены для совместимости .env)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None

    # AI Provider (groq, google, ollama, openai, anthropic)
    ai_provider: str = "groq"

    # Ollama settings (FREE - локально)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Groq settings (FREE - API с лимитами)
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # Google Gemini settings (FREE - тариф с лимитами)
    google_api_key: str | None = None
    google_model: str = "gemini-2.0-flash"

    # OpenAI settings (ПЛАТНО)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Anthropic settings (ПЛАТНО)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # RAG settings
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    chroma_persist_directory: str = "data/chroma"

    # Content planning
    content_plan_weeks: int = 4
    posts_per_week: int = 7

    # Data paths
    data_dir: Path = Path("data")
    posts_db_path: Path = Path("data/posts.db")
    session_name: str = "content_generator"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Создаем директории если их нет
        self.data_dir.mkdir(exist_ok=True)
        Path(self.chroma_persist_directory).mkdir(parents=True, exist_ok=True)


# Глобальный экземпляр настроек
settings = Settings()
