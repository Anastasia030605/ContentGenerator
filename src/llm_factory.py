"""Фабрика LLM и реестр доступных моделей.

Здесь живёт вся логика «какие провайдеры и модели мы поддерживаем» и
«как создать LLM по выбору пользователя». Бэкенд отдаёт реестр на фронт
для dropdown'а, а при генерации создаёт LLM через `build_llm(...)`.
"""

import json
import os
import requests
from dataclasses import dataclass
from typing import Optional

from .config import settings


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    is_free: bool
    requires_key: bool
    key_env_var: Optional[str]
    models: list[ModelOption]


# Реестр того, что отдаётся фронту для построения UI.
# Дефолтный фокус — бесплатные облачные провайдеры (Groq и Gemini).
# Остальные оставлены для BYOK-сценариев, если фронт захочет их показать.
PROVIDERS: dict[str, ProviderInfo] = {
    "groq": ProviderInfo(
        id="groq",
        label="Groq (бесплатно)",
        is_free=True,
        requires_key=True,
        key_env_var="GROQ_API_KEY",
        models=[
            ModelOption("llama-3.3-70b-versatile", "Llama 3.3 70B", "Качественная, быстрая"),
            ModelOption("llama-3.1-8b-instant", "Llama 3.1 8B", "Самая быстрая"),
            ModelOption("qwen/qwen3-32b", "Qwen 3 32B", "Хороша для русского"),
        ],
    ),
    "google": ProviderInfo(
        id="google",
        label="Google Gemini (бесплатно)",
        is_free=True,
        requires_key=True,
        key_env_var="GOOGLE_API_KEY",
        models=[
            ModelOption("gemini-2.0-flash", "Gemini 2.0 Flash", "Быстрая, бесплатный тариф"),
            ModelOption("gemini-2.5-flash", "Gemini 2.5 Flash", "Новее, чуть умнее"),
            ModelOption("gemini-2.5-pro", "Gemini 2.5 Pro", "Самая умная, лимиты строже"),
        ],
    ),
    "ollama": ProviderInfo(
        id="ollama",
        label="Ollama (локально)",
        is_free=True,
        requires_key=False,
        key_env_var=None,
        models=[
            ModelOption("llama3.2:3b", "Llama 3.2 3B", "Лёгкая, для слабого железа"),
            ModelOption("llama3.1:8b", "Llama 3.1 8B", "Средняя"),
            ModelOption("qwen2.5:7b", "Qwen 2.5 7B", "Хороша для русского"),
        ],
    ),
    "demo": ProviderInfo(
        id="demo",
        label="Демо-режим",
        is_free=True,
        requires_key=False,
        key_env_var=None,
        models=[
            ModelOption("demo", "Демо модель", "Работает без API и ключей"),
        ],
    ),
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI (платно, BYOK)",
        is_free=False,
        requires_key=True,
        key_env_var="OPENAI_API_KEY",
        models=[
            ModelOption("gpt-4o-mini", "GPT-4o mini", "Дешёвая"),
            ModelOption("gpt-4o", "GPT-4o", "Топовая"),
        ],
    ),
    "anthropic": ProviderInfo(
        id="anthropic",
        label="Anthropic Claude (платно, BYOK)",
        is_free=False,
        requires_key=True,
        key_env_var="ANTHROPIC_API_KEY",
        models=[
            ModelOption("claude-3-5-haiku-latest", "Claude 3.5 Haiku", "Дешевле"),
            ModelOption("claude-sonnet-4-5", "Claude Sonnet 4.5", "Топовая"),
        ],
    ),
}


def list_providers(only_free: bool = False) -> list[dict]:
    """Сериализованный реестр для отдачи фронту."""
    result = []
    for p in PROVIDERS.values():
        if only_free and not p.is_free:
            continue
        result.append({
            "id": p.id,
            "label": p.label,
            "is_free": p.is_free,
            "requires_key": p.requires_key,
            "key_env_var": p.key_env_var,
            "models": [
                {"id": m.id, "label": m.label, "description": m.description}
                for m in p.models
            ],
        })
    return result


class DummyLLM:
    """Простая локальная заглушка для демонстрации работы генерации."""

    def invoke(self, messages):
        prompt = "\n".join(
            getattr(message, 'content', str(message)) for message in messages
        )
        lower = prompt.lower()

        if "контент-план" in lower or "создай контент-план" in lower:
            plan = [
                {
                    "week": 1,
                    "day": "Понедельник",
                    "time": "10:00",
                    "topic": "Идея для поста",
                    "format": "text",
                    "description": "Простой пост для привлечения внимания аудитории.",
                    "goal": "Вовлечение аудитории"
                },
                {
                    "week": 1,
                    "day": "Среда",
                    "time": "18:00",
                    "topic": "Полезный трюк",
                    "format": "photo",
                    "description": "Пост с наглядным примером и краткой инструкцией.",
                    "goal": "Обучение"
                }
            ]
            return json.dumps(plan, ensure_ascii=False, indent=2)

        topic = "тема"
        if "создай пост на тему:" in lower:
            key = "создай пост на тему:"
            idx = lower.find(key) + len(key)
            # ищем конец строки или перенос
            end = prompt.find("\n", idx)
            if end != -1:
                topic = prompt[idx:end].strip()
            else:
                topic = prompt[idx:].strip()
        elif "topic:" in lower:
            key = "topic:"
            idx = lower.find(key) + len(key)
            end = prompt.find("\n", idx)
            if end != -1:
                topic = prompt[idx:end].strip()
            else:
                topic = prompt[idx:].strip()

        return (
            f"Демо-пост на тему '{topic}'.\n"
            "Этот текст сгенерирован локально без обращения к внешнему API.\n"
            "Используйте этот режим, чтобы быстро проверить интерфейс и структуру выходных данных."
        )

def build_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.8,
):
    """Создать LLM по выбору пользователя.

    Если provider/model/api_key не заданы — берётся из settings.
    `api_key` позволяет BYOK: фронт может передать ключ из формы пользователя.
    """
    provider = (provider or settings.ai_provider).lower()

    if provider == "demo":
        return DummyLLM()

    if provider == "groq":
        try:
            from langchain_groq import ChatGroq
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-groq не установлен. Установите его через requirements.txt или pip install langchain-groq"
            ) from exc
        model = model or settings.groq_model
        key = api_key or settings.groq_api_key
        if not key:
            # Проверяем, возможно, ключ есть в окружении, но не загрузился
            env_key = os.getenv("GROQ_API_KEY")
            if env_key:
                key = env_key
            else:
                raise ValueError(
                    "Не задан GROQ_API_KEY. Получите бесплатный ключ на https://console.groq.com/keys\n"
                    "Добавьте ключ в переменную окружения GROQ_API_KEY или введите его в поле 'API-ключ (BYOK)'.\n"
                    "Если вы хотите использовать демо-режим, выберите провайдер 'Демо-режим'."
                )
        return ChatGroq(api_key=key, model=model, temperature=temperature)

    if provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-google-genai не установлен. Установите его через requirements.txt или pip install langchain-google-genai"
            ) from exc
        model = model or settings.google_model
        key = api_key or settings.google_api_key
        if not key:
            env_key = os.getenv("GOOGLE_API_KEY")
            if env_key:
                key = env_key
            else:
                raise ValueError(
                    "Не задан GOOGLE_API_KEY. Получите бесплатный ключ на https://aistudio.google.com/apikey\n"
                    "Добавьте ключ в переменную окружения GOOGLE_API_KEY или введите его в поле 'API-ключ (BYOK)'.\n"
                    "Если вы хотите использовать демо-режим, выберите провайдер 'Демо-режим'."
                )
        return ChatGoogleGenerativeAI(google_api_key=key, model=model, temperature=temperature)

    if provider == "ollama":
        try:
            from langchain_community.llms import Ollama
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-community не установлен."
            ) from exc

        model = model or settings.ollama_model

        # Проверяем Ollama
        try:
            response = requests.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=5
            )
            response.raise_for_status()

            installed_models = [
                m["name"]
                for m in response.json().get("models", [])
            ]

        except Exception as exc:
            raise ValueError(
                "Ollama не запущен.\n"
                "Запустите Docker Compose или локальный Ollama."
            ) from exc

        # Автозагрузка модели
        if model not in installed_models:
            try:
                pull_response = requests.post(
                    f"{settings.ollama_base_url}/api/pull",
                    json={"name": model},
                    stream=True,
                    timeout=None
                )

                pull_response.raise_for_status()

                for line in pull_response.iter_lines():
                    if line:
                        print(line.decode())
                print(f"[OLLAMA] Модель {model} успешно загружена")

            except Exception as exc:
                raise ValueError(
                    f"Не удалось скачать модель {model} через Ollama."
                ) from exc

        return Ollama(
            base_url=settings.ollama_base_url,
            model=model,
            temperature=temperature
        )

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-openai не установлен. Установите его через requirements.txt или pip install langchain-openai"
            ) from exc
        model = model or settings.openai_model
        key = api_key or settings.openai_api_key
        if not key:
            raise ValueError("Не задан OPENAI_API_KEY")
        return ChatOpenAI(api_key=key, model=model, temperature=temperature)

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-anthropic не установлен. Установите его через requirements.txt или pip install langchain-anthropic"
            ) from exc
        model = model or settings.anthropic_model
        key = api_key or settings.anthropic_api_key
        if not key:
            raise ValueError("Не за��ан ANTHROPIC_API_KEY")
        return ChatAnthropic(api_key=key, model=model, temperature=temperature)

    raise ValueError(
        f"Неизвестный провайдер: {provider}. Доступные: {', '.join(PROVIDERS.keys())}"
    )