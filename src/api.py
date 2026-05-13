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

import json
import math
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .llm_factory import build_llm, list_providers
from .telegram_client import TelegramDataCollector
from .analyzer import PostAnalyzer
from .content_planner import ContentPlanner
from .rag_generator import RAGPostGenerator


app = FastAPI(title="ContentGenerator API", version="0.1.0")

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
        _rag = RAGPostGenerator()
    if require_collection and _rag.collection is None:
        if not _rag.load_collection():
            raise HTTPException(
                status_code=400,
                detail="Векторное хранилище не найдено. Сначала вызовите POST /api/index",
            )
    return _rag


def get_collector() -> TelegramDataCollector:
    global _collector
    if _collector is None:
        _collector = TelegramDataCollector()
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


# ===== Базовые =====

@app.get("/api/health")
def health():
    return {"status": "ok", "channel": settings.telegram_channel_username}


@app.get("/api/models")
def get_models(only_free: bool = False):
    """Список провайдеров и моделей для построения dropdown'а на фронте."""
    return {"providers": list_providers(only_free=only_free)}


# ===== Сбор постов / инфо о канале =====

@app.get("/api/channel-info")
async def channel_info():
    collector = get_collector()
    try:
        return await collector.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Не удалось получить инфо о канале: {e}")


@app.post("/api/collect", response_model=CollectResponse)
async def collect(req: CollectRequest):
    collector = get_collector()
    try:
        await collector.connect()
        posts = await collector.collect_posts(limit=req.limit, days_back=req.days_back)
        collector.save_posts(posts)
        return CollectResponse(collected=len(posts), channel=collector.channel_username)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка сбора: {e}")
    finally:
        await collector.disconnect()


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
        raise HTTPException(status_code=400, detail="Нет постов в БД. Сначала вызовите POST /api/collect")
    analyzer = PostAnalyzer(posts)
    return _clean_floats(analyzer.generate_insights())


# ===== Индексация =====

@app.post("/api/index")
def index_posts():
    collector = get_collector()
    posts = collector.load_posts()
    if not posts:
        raise HTTPException(status_code=400, detail="Нет постов в БД. Сначала вызовите POST /api/collect")
    rag = get_rag(require_collection=False)
    try:
        rag.index_posts(posts)
        return {"indexed": rag.collection.count(), "collection": "channel_posts"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===== Контент-план =====

@app.post("/api/content-plan")
def create_content_plan(req: ContentPlanRequest):
    collector = get_collector()
    posts = collector.load_posts()
    if not posts:
        raise HTTPException(status_code=400, detail="Нет постов в БД. Сначала вызовите POST /api/collect")
    analyzer = PostAnalyzer(posts)
    try:
        planner = ContentPlanner(
            analyzer,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
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
    rag = get_rag()
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


@app.post("/api/refine-post", response_model=GenerateResponse)
def refine_post(req: RefinePostRequest):
    rag = get_rag()
    try:
        post = rag.refine_post(feedback=req.feedback)
        return GenerateResponse(post=post, provider=rag.provider, model=rag.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/generate-from-plan")
def generate_from_plan(req: GenerateFromPlanRequest):
    rag = get_rag()

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
