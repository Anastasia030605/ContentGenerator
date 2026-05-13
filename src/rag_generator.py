"""RAG генератор для создания постов в стиле канала"""

from typing import List, Dict, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from langchain_core.messages import HumanMessage, SystemMessage

from .config import settings
from .llm_factory import build_llm
from .telegram_client import PostMetrics, TelegramDataCollector
from .analyzer import PostAnalyzer


class RAGPostGenerator:
    """Генератор постов на основе RAG (Retrieval-Augmented Generation)"""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self.embedding_model = SentenceTransformer(settings.embedding_model)
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = None
        self.provider = provider or settings.ai_provider
        self.model = model
        self.api_key = api_key
        self.llm = build_llm(provider=self.provider, model=self.model, api_key=self.api_key)

    def index_posts(self, posts: List[PostMetrics], collection_name: str = "channel_posts"):
        """
        Индексирование постов в векторное хранилище

        Args:
            posts: Список постов для индексации
            collection_name: Имя коллекции в ChromaDB
        """
        # Удаляем старую коллекцию если есть
        try:
            self.chroma_client.delete_collection(name=collection_name)
        except:
            pass

        # Создаем новую коллекцию
        self.collection = self.chroma_client.create_collection(
            name=collection_name,
            metadata={"description": "Telegram channel posts for RAG"}
        )

        # Фильтруем посты с текстом
        valid_posts = [p for p in posts if p.text and len(p.text.strip()) > 10]

        if not valid_posts:
            raise ValueError("Нет постов с текстом для индексации")

        print(f"Индексирую {len(valid_posts)} постов...")

        # Генерируем эмбеддинги
        texts = [p.text for p in valid_posts]
        embeddings = self.embedding_model.encode(texts, show_progress_bar=True)

        # Добавляем в ChromaDB
        ids = [f"post_{p.post_id}" for p in valid_posts]
        metadatas = [
            {
                "post_id": str(p.post_id),
                "date": p.date.isoformat(),
                "views": p.views,
                "engagement_rate": (p.forwards + sum(p.reactions.values()) + p.replies) / max(p.views, 1),
                "media_type": p.media_type or "none"
            }
            for p in valid_posts
        ]

        self.collection.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=metadatas
        )

        print(f"[OK] Проиндексировано {len(valid_posts)} постов в коллекцию '{collection_name}'")

    def load_collection(self, collection_name: str = "channel_posts"):
        """Загрузка существующей коллекции"""
        try:
            self.collection = self.chroma_client.get_collection(name=collection_name)
            count = self.collection.count()
            print(f"[OK] Загружена коллекция '{collection_name}' ({count} постов)")
            return True
        except Exception as e:
            print(f"Ошибка загрузки коллекции: {e}")
            return False

    def find_similar_posts(
        self,
        query: str,
        n_results: int = 5,
        min_engagement: float = 0.0
    ) -> List[Dict]:
        """
        Поиск похожих постов по запросу

        Args:
            query: Текст запроса
            n_results: Количество результатов
            min_engagement: Минимальный engagement rate
        """
        if not self.collection:
            if not self.load_collection():
                raise ValueError("Коллекция не загружена. Сначала проиндексируйте посты.")

        # Генерируем эмбеддинг запроса
        query_embedding = self.embedding_model.encode([query])[0]

        # Ищем похожие посты
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=min(n_results * 2, self.collection.count()),  # Берем больше для фильтрации
        )

        # Фильтруем по engagement
        similar_posts = []
        for i in range(len(results['ids'][0])):
            metadata = results['metadatas'][0][i]
            if metadata['engagement_rate'] >= min_engagement:
                similar_posts.append({
                    'post_id': metadata['post_id'],
                    'text': results['documents'][0][i],
                    'views': metadata['views'],
                    'engagement_rate': metadata['engagement_rate'],
                    'distance': results['distances'][0][i] if 'distances' in results else 0
                })

            if len(similar_posts) >= n_results:
                break

        return similar_posts

    def generate_post(
        self,
        topic: str,
        format_type: str = "text",
        additional_context: str = "",
        use_similar_posts: bool = True,
        n_similar: int = 5
    ) -> str:
        """
        Генерация поста в стиле канала

        Args:
            topic: Тема поста
            format_type: Формат поста (text, photo, video, poll)
            additional_context: Дополнительный контекст
            use_similar_posts: Использовать похожие посты для контекста
            n_similar: Количество похожих постов
        """
        # Находим похожие посты для контекста
        similar_posts_context = ""
        if use_similar_posts:
            similar_posts = self.find_similar_posts(
                query=topic,
                n_results=n_similar,
                min_engagement=0.0
            )

            if similar_posts:
                similar_posts_context = "\n\nПримеры успешных постов канала:\n"
                for i, post in enumerate(similar_posts[:3], 1):
                    similar_posts_context += f"\n{i}. (Просмотры: {post['views']})\n{post['text']}\n"

        # Формируем промпт
        system_prompt = f"""Ты - копирайтер Telegram канала. Твоя задача - создать пост в стиле этого канала.

Важно:
1. Изучи примеры постов и повтори их стиль, тон, структуру
2. Используй похожую длину текста
3. Сохрани характерные особенности: эмодзи, форматирование, обращение к аудитории
4. Создай оригинальный контент, не копируй примеры напрямую
5. Формат поста: {format_type}

{f"Контекст: {additional_context}" if additional_context else ""}"""

        user_prompt = f"""Создай пост на тему: {topic}

{similar_posts_context}

Напиши только текст поста, без комментариев и пояснений."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        print(f"Генерирую пост на тему: {topic}...")
        response = self.llm.invoke(messages)

        generated_post = response.content.strip() if hasattr(response, 'content') else response.strip()
        print(f"[OK] Пост создан ({len(generated_post)} символов)")

        self._last_messages = messages
        self._last_post = generated_post

        return generated_post

    def refine_post(self, feedback: str) -> str:
        """
        Улучшение последнего поста на основе обратной связи

        Args:
            feedback: Замечания пользователя
        """
        if not hasattr(self, '_last_messages') or not self._last_messages:
            raise ValueError("Нет предыдущего поста для улучшения. Сначала сгенерируйте пост.")

        # Добавляем в историю предыдущий ответ и фидбек
        from langchain_core.messages import AIMessage
        self._last_messages.append(AIMessage(content=self._last_post))
        self._last_messages.append(HumanMessage(
            content=f"Переделай пост с учётом замечаний: {feedback}\n\nНапиши только текст поста, без комментариев и пояснений."
        ))

        print(f"Улучшаю пост...")
        response = self.llm.invoke(self._last_messages)

        generated_post = response.content.strip() if hasattr(response, 'content') else response.strip()
        print(f"[OK] Пост обновлён ({len(generated_post)} символов)")

        self._last_post = generated_post

        return generated_post

    def generate_posts_from_plan(
        self,
        content_plan: List[Dict],
        save_to_file: Optional[str] = None
    ) -> List[Dict]:
        """
        Генерация постов на основе контент-плана

        Args:
            content_plan: Контент-план
            save_to_file: Путь для сохранения результата
        """
        generated_posts = []

        print(f"\nГенерирую {len(content_plan)} постов...\n")

        for i, plan_item in enumerate(content_plan, 1):
            print(f"[{i}/{len(content_plan)}] Неделя {plan_item['week']}, {plan_item['day']}")

            # Формируем контекст из описания
            context = f"Цель: {plan_item['goal']}. {plan_item['description']}"

            # Генерируем пост
            post_text = self.generate_post(
                topic=plan_item['topic'],
                format_type=plan_item['format'],
                additional_context=context,
                use_similar_posts=True,
                n_similar=5
            )

            # Добавляем к плану
            result = plan_item.copy()
            result['generated_text'] = post_text

            generated_posts.append(result)
            print()

        # Сохраняем если нужно
        if save_to_file:
            import json
            with open(save_to_file, 'w', encoding='utf-8') as f:
                json.dump(generated_posts, f, ensure_ascii=False, indent=2)
            print(f"[OK] Посты сохранены в {save_to_file}")

        return generated_posts

    def analyze_style(self, posts: List[PostMetrics]) -> Dict:
        """Анализ стиля канала для лучшей генерации"""
        analyzer = PostAnalyzer(posts)

        # Собираем характеристики стиля
        style_features = {
            'avg_length': analyzer.df['text_length'].mean(),
            'emoji_usage': analyzer.df['has_emoji'].mean(),
            'link_usage': analyzer.df['has_link'].mean(),
            'hashtag_usage': analyzer.df['has_hashtag'].mean(),
            'media_types': analyzer.df['media_type'].value_counts().to_dict(),
            'popular_keywords': analyzer.extract_successful_keywords(top_n=20)
        }

        return style_features


