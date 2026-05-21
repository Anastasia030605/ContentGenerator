"""Клиент для сбора данных из публичных Telegram каналов через веб-превью t.me/s/"""

import sqlite3
import re
import httpx
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup
import json

from .config import settings


@dataclass
class PostMetrics:
    """Метрики поста"""
    post_id: int
    date: datetime
    text: str
    views: int
    forwards: int
    replies: int
    reactions: Dict[str, int]
    media_type: Optional[str] = None

    def to_dict(self) -> dict:
        """Преобразование в словарь"""
        data = asdict(self)
        data['date'] = self.date.isoformat()
        data['reactions'] = json.dumps(self.reactions)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'PostMetrics':
        """Создание из словаря"""
        data = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        data['date'] = datetime.fromisoformat(data['date'])
        data['reactions'] = json.loads(data['reactions']) if isinstance(data['reactions'], str) else data['reactions']
        return cls(**data)


class TelegramDataCollector:
    """Сборщик данных из публичного Telegram канала через веб-превью"""

    BASE_URL = "https://t.me/s"

    def __init__(self, channel_username: str | None = None):
        channel = channel_username or settings.telegram_channel_username
        if not channel:
            raise ValueError("Не задан Telegram-канал. Укажите channel_username в запросе или в .env файле.")
        self.channel_username = channel.lstrip('@')
        self.db_path = settings.posts_db_path
        self._init_database()

    def _init_database(self):
        """Инициализация базы данных для хранения постов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                post_id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                text TEXT,
                views INTEGER DEFAULT 0,
                forwards INTEGER DEFAULT 0,
                replies INTEGER DEFAULT 0,
                reactions TEXT,
                media_type TEXT,
                updated_at TEXT
            )
        ''')
        conn.commit()
        conn.close()

    async def connect(self):
        """Проверка доступности канала (заглушка для совместимости)"""
        url = f"{self.BASE_URL}/{self.channel_username}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                raise ConnectionError(
                    f"Не удалось получить доступ к каналу @{self.channel_username}. "
                    f"Убедитесь, что канал публичный и имя указано верно."
                )
        print(f"[OK] Канал @{self.channel_username} доступен")

    async def disconnect(self):
        """Заглушка для совместимости"""
        pass

    async def get_channel_info(self) -> dict:
        """Получение информации о канале"""
        url = f"https://t.me/{self.channel_username}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        title_tag = soup.select_one('.tgme_page_title span')
        title = title_tag.get_text(strip=True) if title_tag else self.channel_username

        desc_tag = soup.select_one('.tgme_page_description')
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        subs_tag = soup.select_one('.tgme_page_extra')
        subscribers = 0
        if subs_tag:
            subs_text = subs_tag.get_text(strip=True)
            # Парсим "12 345 subscribers" или "12 345 подписчиков"
            nums = re.findall(r'[\d\s]+', subs_text)
            if nums:
                subscribers = int(nums[0].replace(' ', '').replace('\xa0', ''))

        return {
            'title': title,
            'username': self.channel_username,
            'subscribers': subscribers,
            'description': description
        }

    async def collect_posts(self, limit: int = 100, days_back: Optional[int] = None) -> List[PostMetrics]:
        """
        Сбор постов из канала через веб-превью

        Args:
            limit: Максимальное количество постов
            days_back: Собрать посты за последние N дней
        """
        posts = []
        min_date = None
        if days_back:
            # Создаем дату с часовым поясом UTC для корректного сравнения
            min_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        print(f"Собираю посты из канала @{self.channel_username}...")

        # Первый запрос — последние посты
        url = f"{self.BASE_URL}/{self.channel_username}"
        before_id = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(posts) < limit:
                page_url = url if before_id is None else f"{url}?before={before_id}"
                resp = await client.get(page_url, follow_redirects=True)

                if resp.status_code != 200:
                    print(f"  Ошибка загрузки страницы: {resp.status_code}")
                    break

                soup = BeautifulSoup(resp.text, 'html.parser')
                message_widgets = soup.select('.tgme_widget_message_wrap')

                if not message_widgets:
                    break

                page_posts = []
                for widget in message_widgets:
                    post = self._parse_message_widget(widget)
                    if post is None:
                        continue

                    if min_date:
                        # Гарантируем, что обе даты имеют часовой пояс для сравнения
                        post_date_with_tz = post.date
                        if post_date_with_tz.tzinfo is None:
                            post_date_with_tz = post_date_with_tz.replace(tzinfo=timezone.utc)
                        
                        if post_date_with_tz < min_date:
                            # Достигли предела по дате
                            if page_posts:
                                posts.extend(page_posts)
                            print(f"  Достигнут лимит по дате ({days_back} дней)")
                            return posts[:limit]

                    page_posts.append(post)

                if not page_posts:
                    break

                posts.extend(page_posts)

                if len(posts) % 20 == 0 or len(posts) >= limit:
                    print(f"  Собрано {len(posts)} постов...")

                # Для пагинации берём минимальный ID на странице
                min_id = min(p.post_id for p in page_posts)
                if before_id is not None and min_id >= before_id:
                    break  # Нет новых постов
                before_id = min_id

        posts = posts[:limit]
        print(f"[OK] Собрано {len(posts)} постов")
        return posts

    def _parse_message_widget(self, widget) -> Optional[PostMetrics]:
        """Парсинг одного виджета сообщения"""
        try:
            # Получаем элемент сообщения
            msg_el = widget.select_one('.tgme_widget_message')
            if not msg_el:
                return None

            # ID поста
            data_post = msg_el.get('data-post', '')
            if '/' not in data_post:
                return None
            post_id = int(data_post.split('/')[-1])

            # Текст поста
            text_el = msg_el.select_one('.tgme_widget_message_text')
            text = text_el.get_text(separator='\n', strip=True) if text_el else ""

            # Дата
            date_el = msg_el.select_one('.tgme_widget_message_date time')
            if date_el and date_el.get('datetime'):
                date_str = date_el['datetime']
                # Telegram возвращает дату в UTC с 'Z' в конце
                if date_str.endswith('Z'):
                    date = datetime.fromisoformat(date_str[:-1] + '+00:00')
                else:
                    date = datetime.fromisoformat(date_str)
            else:
                date = datetime.now(timezone.utc)

            # Просмотры
            views = 0
            views_el = msg_el.select_one('.tgme_widget_message_views')
            if views_el:
                views = self._parse_count(views_el.get_text(strip=True))

            # Тип медиа
            media_type = None
            if msg_el.select_one('.tgme_widget_message_photo'):
                media_type = "photo"
            elif msg_el.select_one('.tgme_widget_message_video'):
                media_type = "video"
            elif msg_el.select_one('.tgme_widget_message_document'):
                media_type = "document"
            elif msg_el.select_one('.tgme_widget_message_poll'):
                media_type = "poll"

            # Пропускаем сервисные сообщения без текста и медиа
            if not text and not media_type:
                return None

            return PostMetrics(
                post_id=post_id,
                date=date,
                text=text,
                views=views,
                forwards=0,
                replies=0,
                reactions={},
                media_type=media_type
            )

        except Exception as e:
            print(f"Ошибка при парсинге сообщения: {e}")
            return None

    @staticmethod
    def _parse_count(text: str) -> int:
        """Парсинг чисел вида '1.2K', '3.4M', '567'"""
        text = text.strip().upper()
        if not text:
            return 0
        try:
            if text.endswith('K'):
                return int(float(text[:-1]) * 1000)
            elif text.endswith('M'):
                return int(float(text[:-1]) * 1000000)
            else:
                return int(text.replace(' ', '').replace('\xa0', ''))
        except (ValueError, IndexError):
            return 0

    def save_posts(self, posts: List[PostMetrics]):
        """Сохранение постов в базу данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for post in posts:
            data = post.to_dict()
            data['updated_at'] = datetime.now(timezone.utc).isoformat()

            cursor.execute('''
                INSERT OR REPLACE INTO posts
                (post_id, date, text, views, forwards, replies, reactions, media_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['post_id'], data['date'], data['text'],
                data['views'], data['forwards'], data['replies'],
                data['reactions'], data['media_type'], data['updated_at']
            ))

        conn.commit()
        conn.close()
        print(f"[OK] Сохранено {len(posts)} постов в базу данных")

    def load_posts(self) -> List[PostMetrics]:
        """Загрузка постов из базы данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM posts ORDER BY date DESC')
        rows = cursor.fetchall()
        conn.close()

        posts = []
        for row in rows:
            posts.append(PostMetrics.from_dict(dict(row)))

        return posts