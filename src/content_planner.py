"""Модуль для построения контент-плана на основе анализа"""

from typing import List, Dict
from datetime import datetime, timedelta
import json

from .config import settings
from .analyzer import PostAnalyzer
from .llm_factory import build_llm


class ContentPlanner:
    """Планировщик контента на основе инсайтов"""

    def __init__(
        self,
        analyzer: PostAnalyzer,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self.analyzer = analyzer
        self.insights = analyzer.generate_insights()
        self.llm = build_llm(provider=provider, model=model, api_key=api_key, temperature=0.7)

    def _format_insights_for_prompt(self) -> str:
        """Форматирование инсайтов для промпта"""
        insights_text = f"""
## Статистика канала:
- Всего постов проанализировано: {self.insights['summary']['total_posts']}
- Средние просмотры: {self.insights['summary']['avg_views']:.0f}
- Средний engagement rate: {self.insights['summary']['avg_engagement_rate']:.2%}
- Средняя длина текста: {self.insights['summary']['avg_text_length']:.0f} символов

## Лучшее время публикации:
- Час: {self.insights['best_timing'].get('best_hour', 12)}:00
- День недели: {self.insights['best_timing'].get('best_day', 'Понедельник')}

## Популярные темы и слова:
{', '.join([word for word, _ in self.insights['keywords'][:15]])}

## Топ-5 постов по engagement:
"""
        for i, post in enumerate(self.insights['top_posts'][:5], 1):
            text_preview = post['text'][:100] + '...' if len(post['text']) > 100 else post['text']
            insights_text += f"{i}. Просмотры: {post['views']}, ER: {post['engagement_rate']:.2%}\n   \"{text_preview}\"\n\n"

        if self.insights['recommendations']:
            insights_text += "\n## Рекомендации:\n"
            for rec in self.insights['recommendations']:
                insights_text += f"- {rec}\n"

        return insights_text

    def _distribute_days(self, content_plan: List[Dict]) -> List[Dict]:
        """
        Проверяет и исправляет распределение постов по дням нед��ли.
        Если в какой-либо неделе все посты сконцентрированы в один день, равномерно распределяет их.
        """
        if not content_plan:
            return content_plan
        
        # Группируем по неделям
        weeks = {}
        for item in content_plan:
            week = item.get('week', 1)
            if week not in weeks:
                weeks[week] = []
            weeks[week].append(item)
        
        days_of_week = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        best_hour = self.insights['best_timing'].get('best_hour', 12)
        
        modified = False
        
        for week_num, week_items in weeks.items():
            if len(week_items) <= 1:
                continue
                
            # Проверяем, все ли посты в одной неделе имеют одинаковый день
            unique_days = set(item.get('day') for item in week_items)
            if len(unique_days) == 1:
                # Распределяем посты по дням недели циклически
                for i, item in enumerate(week_items):
                    day_index = i % len(days_of_week)
                    item['day'] = days_of_week[day_index]
                    # Устанавливаем время публикации на основе лучшего часа
                    if not item.get('time') or not item['time'].strip():
                        item['time'] = f"{best_hour:02d}:00"
                modified = True
                print(f"[INFO] Неделя {week_num}: посты распределены по дням недели")
        
        if modified:
            # Собираем обратно все элементы
            result = []
            for week_num in sorted(weeks.keys()):
                result.extend(weeks[week_num])
            return result
        
        return content_plan

    def generate_content_plan(
        self,
        weeks: int = None,
        posts_per_week: int = None,
        additional_instructions: str = ""
    ) -> List[Dict]:
        """
        Генерация контент-плана

        Args:
            weeks: Количество недель (по умолчанию из конфига)
            posts_per_week: Постов в неделю (по умолчанию из конфига)
            additional_instructions: Дополнительные инструкции
        """
        weeks = weeks or settings.content_plan_weeks
        posts_per_week = posts_per_week or settings.posts_per_week

        insights_formatted = self._format_insights_for_prompt()

        system_prompt = """Ты - эксперт по контент-маркетингу и планированию контента для Telegram каналов.
Твоя задача - создать детальный контент-план на основе анализа существующих постов канала.

Учитывай:
1. Статистику и паттерны успешных постов
2. Оптимальное время публикации
3. Популярные темы и форматы
4. Разнообразие контента
5. Вовлечение аудитории

Для каждого поста укажи:
- День недели и время публикации
- Тему поста
- Формат (текст, текст+фото, видео, опрос и т.д.)
- Краткое описание содержания
- Цель поста (информирование, вовлечение, продажи и т.д.)

ВАЖНО:
1. Ты ОБЯЗАН вернуть ТОЛЬКО валидный JSON.
2. НЕ добавляй пояснения.
3. НЕ добавляй markdown.
4. НЕ добавляй текст до или после JSON.
5. Ответ должен начинаться с [ и заканчиваться ].
6. Каждый элемент массива должен быть объектом JSON.
7. Распредели посты равномерно по дням недели.
8. Никакого дополнительного текста вне JSON."""

        user_prompt = f"""На основе анализа канала создай контент-план на {weeks} недель ({posts_per_week} постов в неделю).

{insights_formatted}

{f"Дополнительные требования: {additional_instructions}" if additional_instructions else ""}

Верни результат в формате JSON массива с полями:
- week: номер недели (1-{weeks})
- day: день недели
- time: время публикации (HH:MM)
- topic: тема поста
- format: формат (text, photo, video, poll, etc.)
- description: краткое описание (2-3 предложения)
- goal: цель поста

Пример корректного ответа:

[
  {{
    "week": 1,
    "day": "Понедельник",
    "time": "10:00",
    "topic": "Утренняя мотивация",
    "format": "text",
    "description": "Короткий вдохновляющий пост для начала дня.",
    "goal": "Вовлечение аудитории"
  }},
  {{
    "week": 1,
    "day": "Среда",
    "time": "14:00",
    "topic": "Полезный совет",
    "format": "photo",
    "description": "Практический совет с визуальным оформлением.",
    "goal": "Информирование"
  }}
]

Верни ТОЛЬКО JSON."""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ModuleNotFoundError as exc:
            raise ValueError(
                "Пакет langchain-core не установлен. Установите его через requirements.txt или pip install langchain-core"
            ) from exc

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        print("Генерирую контент-план с помощью LLM...")
        response = self.llm.invoke(messages)

        # Парсим JSON из ответа
        content = response.content if hasattr(response, 'content') else response

        # Извлекаем JSON (может быть в markdown блоке)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        content = content.strip()

        # Пытаемся вытащить JSON-массив даже если модель добавила текст
        start = content.find('[')
        end = content.rfind(']')

        if start != -1 and end != -1:
            content = content[start:end + 1]

        print("\n===== RAW LLM RESPONSE =====")
        print(content)
        print("===== END RAW RESPONSE =====\n")

        try:
            content_plan = json.loads(content)

            print("\n===== PARSED CONTENT PLAN =====")
            print(type(content_plan))
            print(content_plan)
            print("===== END PARSED =====\n")
        except json.JSONDecodeError as e:
            print(f"Ошибка парсинга JSON: {e}")
            print(f"Ответ LLM:\n{content}")
            raise

        # Проверяем и исправляем распределение по дням недели
        content_plan = self._distribute_days(content_plan)

        print(f"[OK] Контент-план создан: {len(content_plan)} постов")
        return content_plan

    def save_content_plan(self, content_plan: List[Dict], filename: str = None):
        """Сохранение контент-плана в файл"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/content_plan_{timestamp}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(content_plan, f, ensure_ascii=False, indent=2)

        print(f"[OK] Контент-план сохранен: {filename}")
        return filename

    def load_content_plan(self, filename: str) -> List[Dict]:
        """Загрузка контент-плана из файла"""
        with open(filename, 'r', encoding='utf-8') as f:
            content_plan = json.load(f)

        print(f"[OK] Контент-план загружен: {len(content_plan)} постов")
        return content_plan

    def print_content_plan(self, content_plan: List[Dict]):
        """Красивый вывод контент-плана"""
        print("\n" + "=" * 80)
        print("КОНТЕНТ-ПЛАН".center(80))
        print("=" * 80)

        current_week = 0
        for item in content_plan:
            if item['week'] != current_week:
                current_week = item['week']
                print(f"\n{'НЕДЕЛЯ ' + str(current_week):^80}")
                print("-" * 80)

            print(f"\n{item['day']}, {item['time']} | {item['format'].upper()}")
            print(f"Тема: {item['topic']}")
            print(f"Описание: {item['description']}")
            print(f"Цель: {item['goal']}")

        print("\n" + "=" * 80)