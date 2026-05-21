"""FastAPI бэкенд для веб-интерфейса.

Запуск:
    uvicorn src.api:app --reload

Эндпоинты:
    GET  /api/health           — проверка живости
    GET  /api/models           — список провайдеров и моделей для dropdown
    POST /api/collect          — собрать посты из Telegram канала
    GET  /api/posts            — список сохранённых постов
    GET  /api/channel-info     — инфо о канале
    POST /api/analyze          — инсайты (статистика, лучшее время, топ постов)
    POST /api/index            — построить векторное хранилище для RAG
    POST /api/content-plan     — сгенерировать контент-план
    GET  /api/content-plans    — список ранее сохранённых планов
    POST /api/generate-post    — сгенерировать один пост
    POST /api/refine-post      — улучшить последний пост
    POST /api/generate-from-plan — сгенерировать посты по контент-плану
"""

# Загрузить переменные окружения из .env
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env", encoding="utf-8", override=True)
except ModuleNotFoundError:
    pass

import json
import math
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .llm_factory import build_llm, list_providers
from .telegram_client import PostMetrics, TelegramDataCollector
from .analyzer import PostAnalyzer
from .content_planner import ContentPlanner
from .rag_generator import RAGPostGenerator


app = FastAPI(title="ContentGenerator API", version="0.1.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def read_root():
    index_file = FRONTEND_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_rag: Optional[RAGPostGenerator] = None
_collector: Optional[TelegramDataCollector] = None


def get_rag(require_collection: bool = True) -> RAGPostGenerator:
    """Ленивая инициализация RAG-генератора (эмбеддинги загружаются один раз)."""
    global _rag
    if _rag is None:
        try:
            _rag = RAGPostGenerator()
        except ValueError as e:
            # Добавляем дополнительные инструкции по установке зависимостей
            error_detail = f"{str(e)}\n\n"
            error_detail += "Для установки всех необходимых зависимостей выполните следующие шаги:\n"
            error_detail += "1. Активируйте виртуальное окружение (если используете)\n"
            error_detail += "2. Установите все зависимости из requirements.txt: pip install -r requirements.txt\n"
            error_detail += "3. Или установите пакеты вручную: pip install chromadb sentence-transformers langchain-core\n"
            error_detail += "4. Перезапустите приложение после установки зависимостей"
            raise HTTPException(
                status_code=500,
                detail=error_detail
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Неожиданная ошибка инициализации RAG-генератора: {str(e)}"
            )
    if require_collection and _rag.collection is None:
        if not _rag.load_collection():
            raise HTTPException(
                status_code=400,
                detail="Векторное хранилище не найдено. Сначала вызовите POST /api/index",
            )
    return _rag


def get_collector(channel_username: Optional[str] = None) -> TelegramDataCollector:
    global _collector
    if channel_username:
        channel_username = channel_username.lstrip('@')
    if _collector is None or (channel_username and channel_username != _collector.channel_username):
        _collector = TelegramDataCollector(channel_username=channel_username)
    return _collector


def _clean_floats(obj: Any) -> Any:
    """Заменить NaN/Inf на None — иначе JSON-сериализация валится."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_floats(v) for v in obj]
    if isinstance(obj, tuple):
        return [_clean_floats(v) for v in obj]
    return obj


# ===== Pydantic схемы =====

class LLMSelection(BaseModel):
    """Общий блок выбора модели — переиспользуется во многих запросах."""
    provider: Optional[str] = Field(None, description="ID провайдера (groq, google, ...)")
    model: Optional[str] = Field(None, description="ID модели в рамках провайдера")
    api_key: Optional[str] = Field(None, description="Опциональный BYOK-ключ, иначе берётся из .env")


class CollectRequest(BaseModel):
    limit: int = 100
    days_back: Optional[int] = None
    channel_username: Optional[str] = None


class CollectResponse(BaseModel):
    collected: int
    channel: str


class ContentPlanRequest(LLMSelection):
    weeks: Optional[int] = None
    posts_per_week: Optional[int] = None
    instructions: str = ""


class GeneratePostRequest(LLMSelection):
    topic: str
    format_type: str = "text"
    additional_context: str = ""
    n_similar: int = 5


class RefinePostRequest(BaseModel):
    feedback: str


class GenerateFromPlanRequest(LLMSelection):
    # либо план inline, либо путь к сохранённому файлу
    content_plan: Optional[list[dict]] = None
    plan_file: Optional[str] = None


class GenerateResponse(BaseModel):
    post: str
    provider: str
    model: Optional[str]


class DemoSetupResponse(BaseModel):
    created: int
    message: str


class StatusResponse(BaseModel):
    posts_count: int
    plans_count: int
    latest_plan: Optional[str] = None
    demo_available: bool = True


# ===== Базовые =====

@app.get("/api/health")
def health():
    return {"status": "ok", "channel": settings.telegram_channel_username}


@app.get("/api/models")
def get_models(only_free: bool = False):
    """Список провайдеров и моделей для построения dropdown'а на фронте."""
    return {"providers": list_providers(only_free=only_free)}


@app.get("/api/status", response_model=StatusResponse)
def status(channel_username: Optional[str] = None):
    collector = get_collector(channel_username=channel_username)
    posts = collector.load_posts()
    plan_files = sorted(Path(settings.data_dir).glob("content_plan_*.json"), reverse=True)
    return StatusResponse(
        posts_count=len(posts),
        plans_count=len(plan_files),
        latest_plan=plan_files[0].name if plan_files else None,
        demo_available=True,
    )


@app.post("/api/demo-setup", response_model=DemoSetupResponse)
def demo_setup():
    collector = get_collector()
    sample_texts = [
        "Сегодня расскажем, как создать идеальный пост для вашего Telegram-канала.",
        "Примеры форматирования: короткий заголовок, эмодзи и призыв к действию.",
        "Почему важен контент-план и как его использовать каждый день.",
        "Обзор полезных инструментов для продвижения канала и роста аудитории.",
        "История успеха: как один пост собрал тысячи просмотров за 24 часа.",
        "Секреты написания цепляющих заголовков для Telegram.",
        "Как собирать идеи для контента и не потерять вдохновение.",
        "Где искать актуальные темы и как адаптировать их под свою аудиторию.",
        "Рекомендации по частоте публикаций и лучшему времени для выхода постов.",
        "Заключение: что важно делать каждый день, чтобы канал рос."
    ]
    now = datetime.now()
    posts = []
    for idx, text in enumerate(sample_texts, start=1):
        posts.append(PostMetrics(
            post_id=1000 + idx,
            date=now - timedelta(days=idx),
            text=text,
            views=500 + idx * 50,
            forwards=5 + idx,
            replies=2 + idx,
            reactions={"like": 10 + idx, "heart": 3 + idx},
            media_type="text",
        ))

    collector.save_posts(posts)
    return DemoSetupResponse(created=len(posts), message="Демонстрационные посты успешно добавлены в базу данных.")


# ===== Сбор постов / инфо о канале =====

@app.get("/api/channel-info")
async def channel_info(channel_username: Optional[str] = None):
    collector = get_collector(channel_username=channel_username)
    try:
        return await collector.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Не удалось получить инфо о канале: {e}")


@app.post("/api/collect", response_model=CollectResponse)
async def collect(req: CollectRequest):
    collector = get_collector(channel_username=req.channel_username)
    try:
        await collector.connect()
        posts = await collector.collect_posts(limit=req.limit, days_back=req.days_back)
        collector.save_posts(posts)
        return CollectResponse(collected=len(posts), channel=collector.channel_username)
    except Exception as e:
        # Логируем полную ошибку для отладки
        print(f"Ошибка сбора постов: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=502, detail=f"Ошибка сбора постов: {e}")
    finally:
        try:
            await collector.disconnect()
        except:
            pass


@app.get("/api/posts")
def list_posts(limit: int = 50, offset: int = 0):
    collector = get_collector()
    posts = collector.load_posts()
    total = len(posts)
    page = posts[offset:offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "post_id": p.post_id,
                "date": p.date.isoformat(),
                "text": p.text,
                "views": p.views,
                "forwards": p.forwards,
                "replies": p.replies,
                "reactions": p.reactions,
                "media_type": p.media_type,
            }
            for p in page
        ],
    }


# ===== Анализ =====

@app.post("/api/analyze")
def analyze():
    collector = get_collector()
    posts = collector.load_posts()
    if not posts:
        raise HTTPException(status_code=400, detail="Сначала соберите посты. Нажмите 'Заполнить демонстрационными постами' или 'Собрать посты' из Telegram канала.")
    try:
        analyzer = PostAnalyzer(posts)
        insights = analyzer.generate_insights()
        return _clean_floats(insights)
    except Exception as e:
        # Логируем полную ошибку для отладки
        print(f"Ошибка анализа канала: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Ошибка анализа канала: {e}")


# ===== Индексация =====

@app.post("/api/index")
def index_posts():
    collector = get_collector()
    posts = collector.load_posts()
    if not posts:
        raise HTTPException(status_code=400, detail="Сначала соберите посты. Нажмите 'Заполнить демонстрационными постами' или 'Собрать посты' из Telegram канала.")
    try:
        rag = get_rag(require_collection=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка инициализации RAG-генератора: {str(e)}")
    
    try:
        rag.index_posts(posts)
        return {"indexed": rag.collection.count(), "collection": "channel_posts"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Добавляем подробную информацию об ошибке для отладки
        error_detail = f"Ошибка индексирования: {str(e)}\n\n"
        error_detail += "Убедитесь, что установлены все необходимые зависимости:\n"
        error_detail += "1. pip install chromadb sentence-transformers\n"
        error_detail += "2. Или установите все зависимости: pip install -r requirements.txt\n"
        error_detail += "3. Перезапустите приложение после установки"
        print(f"Ошибка индексации: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_detail)


# ===== Контент-план =====

@app.post("/api/content-plan")
def create_content_plan(req: ContentPlanRequest):
    collector = get_collector()
    posts = collector.load_posts()
    if not posts:
        raise HTTPException(status_code=400, detail="Сначала соберите посты. Нажмите 'Заполнить демонстрационными постами' или 'Собрать посты' из Telegram канала.")
    try:
        analyzer = PostAnalyzer(posts)
        # Если ключ не передан, используем из конфига
        api_key = req.api_key or None
        provider = req.provider or settings.ai_provider
        
        planner = ContentPlanner(
            analyzer,
            provider=provider,
            model=req.model,
            api_key=api_key,
        )
        content_plan = planner.generate_content_plan(
            weeks=req.weeks,
            posts_per_week=req.posts_per_week,
            additional_instructions=req.instructions,
        )
        filename = planner.save_content_plan(content_plan)
        return {"plan": content_plan, "saved_to": filename, "count": len(content_plan)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Логируем полную ошибку для отладки
        print(f"Ошибка генерации контент-плана: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Ошибка генерации плана: {e}")


@app.get("/api/content-plans")
def list_content_plans():
    """Список ранее сохранённых планов в data/."""
    files = sorted(Path(settings.data_dir).glob("content_plan_*.json"), reverse=True)
    return {
        "items": [
            {"path": str(f), "name": f.name, "modified": f.stat().st_mtime}
            for f in files
        ]
    }


# ===== Генерация постов =====

@app.post("/api/generate-post", response_model=GenerateResponse)
def generate_post(req: GeneratePostRequest):
    try:
        rag = get_rag()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка иници��лизации RAG-генератора: {str(e)}")
    
    try:
        rag.llm = build_llm(provider=req.provider, model=req.model, api_key=req.api_key)
        rag.provider = req.provider or rag.provider
        rag.model = req.model

        post = rag.generate_post(
            topic=req.topic,
            format_type=req.format_type,
            additional_context=req.additional_context,
            n_similar=req.n_similar,
        )
        return GenerateResponse(post=post, provider=rag.provider, model=req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Логируем полную ошибку для отладки
        print(f"Ошибка генерации поста: {e}")
        print(traceback.format_exc())
        # Добавляем подробную информацию об ошибке
        error_detail = f"Ошибка генерации поста: {str(e)}"
        if "collection" in str(e).lower() or "индекс" in str(e).lower():
            error_detail += "\n\nСначала проиндексируйте посты. Нажмите 'Проиндексировать' после сбора постов."
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/refine-post", response_model=GenerateResponse)
def refine_post(req: RefinePostRequest):
    try:
        rag = get_rag()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка инициализации RAG-генератора: {str(e)}")
    
    try:
        post = rag.refine_post(feedback=req.feedback)
        return GenerateResponse(post=post, provider=rag.provider, model=rag.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Ошибка улучшения поста: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Ошибка улучшения поста: {e}")


@app.post("/api/generate-from-plan")
def generate_from_plan(req: GenerateFromPlanRequest):
    try:
        rag = get_rag()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка инициализации RAG-генератора: {str(e)}")

    if req.content_plan is not None:
        plan = req.content_plan
    elif req.plan_file:
        path = Path(req.plan_file)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Файл не найден: {req.plan_file}")
        plan = json.loads(path.read_text(encoding="utf-8"))
    else:
        # Берём последний сохранённый план
        files = sorted(Path(settings.data_dir).glob("content_plan_*.json"), reverse=True)
        if not files:
            raise HTTPException(
                status_code=400,
                detail="Контент-план не передан и не найден на диске. Вызовите POST /api/content-plan",
            )
        plan = json.loads(files[0].read_text(encoding="utf-8"))

    try:
        rag.llm = build_llm(provider=req.provider, model=req.model, api_key=req.api_key)
        rag.provider = req.provider or rag.provider
        rag.model = req.model

        generated = rag.generate_posts_from_plan(content_plan=plan)
        return {"count": len(generated), "items": generated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Ошибка генерации постов из плана: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Ошибка генерации постов из плана: {e}")