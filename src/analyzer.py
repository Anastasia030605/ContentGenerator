"""Анализатор популярности постов Telegram канала"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime, time, timezone, timedelta
from collections import Counter
import re

# Часовой пояс Москвы (UTC+3)
MSK = timezone(timedelta(hours=3))

from .telegram_client import PostMetrics


class PostAnalyzer:
    """Анализатор постов для выявления успешных паттернов"""

    def __init__(self, posts: List[PostMetrics]):
        self.posts = posts
        self.df = self._posts_to_dataframe()

    def _safe_astimezone(self, dt: datetime, tz: timezone) -> datetime:
        """Безопасное преобразование времени в указанный часовой пояс"""
        if dt is None:
            return None
        # Если datetime не имеет часового пояса, считаем что это UTC
        if dt.tzinfo is None:
            # Добавляем UTC и конвертируем в нужный пояс
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)

    def _ensure_timezone(self, dt: datetime) -> datetime:
        """Гарантирует, что datetime имеет часовой пояс (UTC)"""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def _posts_to_dataframe(self) -> pd.DataFrame:
        """Преобразование постов в DataFrame для анализа"""
        data = []
        for post in self.posts:
            # Гарантируем, что дата имеет часовой пояс
            safe_date = self._ensure_timezone(post.date)
            
            total_reactions = sum(post.reactions.values())
            data.append({
                'post_id': post.post_id,
                'date': safe_date,
                'text': post.text,
                'views': post.views,
                'forwards': post.forwards,
                'replies': post.replies,
                'reactions': total_reactions,
                'media_type': post.media_type,
                'text_length': len(post.text),
                'hour': self._safe_astimezone(safe_date, MSK).hour,
                'day_of_week': self._safe_astimezone(safe_date, MSK).weekday(),
                'has_emoji': bool(re.search(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', post.text)),
                'has_link': bool(re.search(r'http[s]?://|t\.me/', post.text)),
                'has_hashtag': bool(re.search(r'#\w+', post.text)),
            })

        df = pd.DataFrame(data)

        # Рассчитываем engagement rate
        if len(df) > 0 and df['views'].sum() > 0:
            df['engagement_rate'] = (df['reactions'] + df['forwards'] + df['replies']) / df['views'].replace(0, 1)
            df['engagement_score'] = df['engagement_rate'] * df['views']  # Взвешенная метрика
        else:
            df['engagement_rate'] = 0
            df['engagement_score'] = 0

        return df

    def get_top_posts(self, n: int = 10, metric: str = 'engagement_score') -> pd.DataFrame:
        """
        Получение топ-N постов по заданной метрике

        Args:
            n: Количество постов
            metric: Метрика для сортировки (views, engagement_rate, engagement_score)
        """
        return self.df.nlargest(n, metric)[['post_id', 'date', 'text', 'views', 'engagement_rate', metric]]

    def analyze_posting_time(self) -> Dict[str, any]:
        """Анализ лучшего времени для публикации"""
        if len(self.df) == 0:
            return {}

        # Группируем по часам
        hourly_stats = self.df.groupby('hour').agg({
            'views': 'mean',
            'engagement_rate': 'mean',
            'engagement_score': 'mean'
        }).round(2)

        # Группируем по дням недели (0 = Понедельник, 6 = Воскресенье)
        daily_stats = self.df.groupby('day_of_week').agg({
            'views': 'mean',
            'engagement_rate': 'mean',
            'engagement_score': 'mean'
        }).round(2)

        days_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

        return {
            'best_hour': int(hourly_stats['views'].idxmax()) if len(hourly_stats) > 0 else 12,
            'best_day': days_names[int(daily_stats['views'].idxmax())] if len(daily_stats) > 0 else 'Понедельник',
            'hourly_stats': hourly_stats.to_dict(),
            'daily_stats': {days_names[i]: daily_stats.loc[i].to_dict() for i in range(7) if i in daily_stats.index}
        }

    def analyze_content_patterns(self) -> Dict[str, any]:
        """Анализ паттернов контента"""
        if len(self.df) == 0:
            return {}

        # Сравниваем посты с разными характеристиками
        patterns = {}

        # Влияние медиа
        if 'media_type' in self.df.columns:
            media_stats = self.df.groupby('media_type').agg({
                'views': 'mean',
                'engagement_rate': 'mean'
            }).round(2)
            patterns['media_impact'] = media_stats.to_dict()

        # Влияние длины текста
        self.df['length_category'] = pd.cut(
            self.df['text_length'],
            bins=[0, 100, 300, 500, float('inf')],
            labels=['Короткий', 'Средний', 'Длинный', 'Очень длинный']
        )
        length_stats = self.df.groupby('length_category').agg({
            'views': 'mean',
            'engagement_rate': 'mean'
        }).round(2)
        patterns['length_impact'] = length_stats.to_dict()

        # Влияние эмодзи, ссылок, хештегов
        for feature in ['has_emoji', 'has_link', 'has_hashtag']:
            feature_stats = self.df.groupby(feature).agg({
                'views': 'mean',
                'engagement_rate': 'mean'
            }).round(2)
            patterns[f'{feature}_impact'] = feature_stats.to_dict()

        return patterns

    def extract_successful_keywords(self, top_n: int = 20) -> List[Tuple[str, float]]:
        """
        Извлечение ключевых слов из успешных постов

        Args:
            top_n: Количество постов для анализа
        """
        # Берем топовые посты
        top_posts = self.get_top_posts(n=top_n, metric='engagement_score')

        # Извлекаем слова (упрощенно - разделение по пробелам)
        all_words = []
        for text in top_posts['text']:
            if pd.isna(text):
                continue
            # Удаляем знаки препинания и приводим к нижнему регистру
            words = re.findall(r'\b[а-яёa-z]{3,}\b', text.lower())
            all_words.extend(words)

        # Подсчитываем частоту
        word_freq = Counter(all_words)

        # Убираем стоп-слова (базовый список)
        stop_words = {'это', 'для', 'как', 'что', 'все', 'или', 'при', 'без', 'так', 'вот', 'еще', 'уже', 'где', 'быть', 'как'}
        filtered_freq = {word: count for word, count in word_freq.items() if word not in stop_words}

        return sorted(filtered_freq.items(), key=lambda x: x[1], reverse=True)[:20]

    def get_summary_statistics(self) -> Dict[str, any]:
        """Получение сводной статистики"""
        if len(self.df) == 0:
            return {
                'total_posts': 0,
                'avg_views': 0,
                'avg_engagement_rate': 0
            }

        # Безопасное получение минимальной и максимальной даты
        try:
            min_date = self.df['date'].min()
            max_date = self.df['date'].max()
            
            # Гарантируем, что даты имеют часовой пояс для isoformat
            min_date_safe = self._ensure_timezone(min_date)
            max_date_safe = self._ensure_timezone(max_date)
            
            date_range = {
                'from': min_date_safe.isoformat(),
                'to': max_date_safe.isoformat()
            }
        except Exception as e:
            # Если возникла ошибка при работе с датами, используем fallback
            print(f"Предупреждение: ошибка при обработке дат: {e}")
            date_range = {
                'from': None,
                'to': None
            }

        return {
            'total_posts': len(self.df),
            'date_range': date_range,
            'avg_views': round(self.df['views'].mean(), 2),
            'median_views': round(self.df['views'].median(), 2),
            'max_views': int(self.df['views'].max()),
            'avg_engagement_rate': round(self.df['engagement_rate'].mean(), 4),
            'median_engagement_rate': round(self.df['engagement_rate'].median(), 4),
            'avg_reactions': round(self.df['reactions'].mean(), 2),
            'avg_forwards': round(self.df['forwards'].mean(), 2),
            'avg_replies': round(self.df['replies'].mean(), 2),
            'avg_text_length': round(self.df['text_length'].mean(), 2),
            'posts_with_media': int(self.df['media_type'].notna().sum()),
            'posts_with_links': int(self.df['has_link'].sum()),
            'posts_with_hashtags': int(self.df['has_hashtag'].sum())
        }

    def generate_insights(self) -> Dict[str, any]:
        """Генерация инсайтов на основе анализа"""
        try:
            insights = {
                'summary': self.get_summary_statistics(),
                'best_timing': self.analyze_posting_time(),
                'content_patterns': self.analyze_content_patterns(),
                'top_posts': self.get_top_posts(n=5, metric='views').to_dict('records'),
                'keywords': self.extract_successful_keywords(top_n=30)
            }

            # Генерируем рекомендации
            recommendations = []

            # Рекомендация по времени
            if 'best_hour' in insights['best_timing']:
                recommendations.append(
                    f"Лучшее время для публикации: {insights['best_timing']['best_hour']}:00, "
                    f"{insights['best_timing']['best_day']}"
                )

            # Рекомендация по медиа
            if 'media_impact' in insights['content_patterns']:
                media_stats = insights['content_patterns']['media_impact'].get('engagement_rate', {})
                if media_stats:
                    best_media = max(media_stats.items(), key=lambda x: x[1] if x[1] is not None else 0)
                    if best_media[0] != 'None':
                        recommendations.append(f"Посты с {best_media[0]} показывают лучший engagement")

            # Рекомендация по длине
            if 'length_impact' in insights['content_patterns']:
                length_stats = insights['content_patterns']['length_impact'].get('engagement_rate', {})
                if length_stats:
                    best_length = max(length_stats.items(), key=lambda x: x[1] if x[1] is not None else 0)
                    recommendations.append(f"Оптимальная длина текста: {best_length[0]}")

            insights['recommendations'] = recommendations

            return insights
        except Exception as e:
            # Возвращаем базовые инсайты при ошибке
            print(f"Ошибка при генерации инсайтов: {e}")
            return {
                'summary': self.get_summary_statistics(),
                'best_timing': {},
                'content_patterns': {},
                'top_posts': [],
                'keywords': [],
                'recommendations': [f"Ошибка анализа: {str(e)}"]
            }