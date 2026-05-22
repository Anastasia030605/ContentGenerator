"""Конфигурация приложения"""

import os
from pathlib import Path

# Загрузить переменные окружения из .env ДО всех остальных операций
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env", encoding="utf-8", override=True)
except ModuleNotFoundError:
    pass

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _USE_PYDANTIC_SETTINGS = True
except ModuleNotFoundError:
    _USE_PYDANTIC_SETTINGS = False

if _USE_PYDANTIC_SETTINGS:
    class Settings(BaseSettings):
        """Настройки приложения"""

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )

        telegram_channel_username: str = ""
        telegram_api_id: int | None = None
        telegram_api_hash: str | None = None
        telegram_phone: str | None = None

        ai_provider: str = "groq"

        ollama_base_url: str = "http://localhost:11434"
        ollama_model: str = "llama3.2:3b"

        groq_api_key: str | None = None
        groq_model: str = "llama-3.3-70b-versatile"

        google_api_key: str | None = None
        google_model: str = "gemini-2.0-flash"

        openai_api_key: str | None = None
        openai_model: str = "gpt-4o-mini"

        anthropic_api_key: str | None = None
        anthropic_model: str | None = None

        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        chroma_persist_directory: str = "data/chroma"

        content_plan_weeks: int = 4
        posts_per_week: int = 7

        data_dir: Path = Path("data")
        posts_db_path: Path = Path("data/posts.db")
        session_name: str = "content_generator"

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.data_dir.mkdir(exist_ok=True)
            Path(self.chroma_persist_directory).mkdir(parents=True, exist_ok=True)
else:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=".env", encoding="utf-8")
    except ModuleNotFoundError:
        pass

    def _to_int(value: str | None, default: int = 0) -> int:
        return int(value) if value and value.isdigit() else default

    class Settings:
        """Настройки приложения без pydantic-settings"""

        telegram_channel_username: str
        telegram_api_id: int | None
        telegram_api_hash: str | None
        telegram_phone: str | None

        ai_provider: str

        ollama_base_url: str
        ollama_model: str

        groq_api_key: str | None
        groq_model: str

        google_api_key: str | None
        google_model: str

        openai_api_key: str | None
        openai_model: str

        anthropic_api_key: str | None
        anthropic_model: str | None

        embedding_model: str
        chroma_persist_directory: str

        content_plan_weeks: int
        posts_per_week: int

        data_dir: Path
        posts_db_path: Path
        session_name: str

        def __init__(self):
            self.telegram_channel_username = os.getenv("TELEGRAM_CHANNEL_USERNAME", "")
            self.telegram_api_id = _to_int(os.getenv("TELEGRAM_API_ID")) if os.getenv("TELEGRAM_API_ID") else None
            self.telegram_api_hash = os.getenv("TELEGRAM_API_HASH")
            self.telegram_phone = os.getenv("TELEGRAM_PHONE")

            self.ai_provider = os.getenv("AI_PROVIDER", "groq")

            self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

            self.groq_api_key = os.getenv("GROQ_API_KEY")
            self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

            self.google_api_key = os.getenv("GOOGLE_API_KEY")
            self.google_model = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")

            self.openai_api_key = os.getenv("OPENAI_API_KEY")
            self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
            self.anthropic_model = os.getenv("ANTHROPIC_MODEL")

            self.embedding_model = os.getenv(
                "EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            )
            self.chroma_persist_directory = os.getenv("CHROMA_PERSIST_DIRECTORY", "data/chroma")

            self.content_plan_weeks = _to_int(os.getenv("CONTENT_PLAN_WEEKS"), 4)
            self.posts_per_week = _to_int(os.getenv("POSTS_PER_WEEK"), 7)

            self.data_dir = Path(os.getenv("DATA_DIR", "data"))
            self.posts_db_path = Path(os.getenv("POSTS_DB_PATH", "data/posts.db"))
            self.session_name = os.getenv("SESSION_NAME", "content_generator")

            self.data_dir.mkdir(exist_ok=True)
            Path(self.chroma_persist_directory).mkdir(parents=True, exist_ok=True)

settings = Settings()
