"""
Content Generator - Сервис для автоматизации контента Telegram каналов

Основные функции:
1. Сбор постов и метрик из Telegram канала
2. Анализ популярности контента
3. Построение контент-плана на N недель
4. Генерация постов в стиле канала через RAG
"""

import asyncio
import argparse
import sys
from pathlib import Path

from src.telegram_client import TelegramDataCollector
from src.analyzer import PostAnalyzer
from src.content_planner import ContentPlanner
from src.rag_generator import RAGPostGenerator
from src.config import settings


class ContentGeneratorApp:
    """Главное приложение Content Generator"""

    def __init__(self):
        self.collector = TelegramDataCollector()
        self.generator = None
        self.analyzer = None
        self.planner = None

    async def collect_posts(self, limit: int = 100, days_back: int = None):
        """Сбор постов из канала"""
        print("\n" + "=" * 80)
        print("СБОР ПОСТОВ ИЗ TELEGRAM КАНАЛА".center(80))
        print("=" * 80 + "\n")

        try:
            await self.collector.connect()

            # Информация о канале
            info = await self.collector.get_channel_info()
            print(f"Канал: {info['title']} (@{info['username']})")
            print(f"Подписчиков: {info['subscribers']}\n")

            # Собираем посты
            posts = await self.collector.collect_posts(limit=limit, days_back=days_back)

            # Сохраняем
            self.collector.save_posts(posts)

            print(f"\n[OK] Успешно собрано и сохранено {len(posts)} постов")

        except Exception as e:
            print(f"\n[!] Ошибка при сборе постов: {e}")
            raise
        finally:
            await self.collector.disconnect()

    def analyze_channel(self):
        """Анализ канала"""
        print("\n" + "=" * 80)
        print("АНАЛИЗ КАНАЛА".center(80))
        print("=" * 80 + "\n")

        # Загружаем посты
        posts = self.collector.load_posts()
        if not posts:
            print("[!] Нет постов в базе данных. Сначала соберите посты командой 'collect'")
            return

        # Создаем анализатор
        self.analyzer = PostAnalyzer(posts)

        # Получаем инсайты
        insights = self.analyzer.generate_insights()

        # Выводим результаты
        print(f"Всего постов: {insights['summary']['total_posts']}")
        print(f"Период: {insights['summary']['date_range']['from'][:10]} - {insights['summary']['date_range']['to'][:10]}")
        print(f"\nСредние просмотры: {insights['summary']['avg_views']:.0f}")
        print(f"Медиана просмотров: {insights['summary']['median_views']:.0f}")
        print(f"Максимум просмотров: {insights['summary']['max_views']}")
        print(f"Средняя длина текста: {insights['summary']['avg_text_length']:.0f} символов")

        print("\n" + "-" * 80)
        print("ОПТИМАЛЬНОЕ ВРЕМЯ ПУБЛИКАЦИИ")
        print("-" * 80)
        print(f"Лучший час: {insights['best_timing']['best_hour']}:00")
        print(f"Лучший день: {insights['best_timing']['best_day']}")

        print("\n" + "-" * 80)
        print("ТОП-5 ПОСТОВ")
        print("-" * 80)
        for i, post in enumerate(insights['top_posts'][:5], 1):
            text_preview = post['text'][:80] + '...' if len(post['text']) > 80 else post['text']
            print(f"\n{i}. Просмотры: {post['views']}")
            print(f"   {text_preview}")

        print("\n" + "-" * 80)
        print("ПОПУЛЯРНЫЕ СЛОВА")
        print("-" * 80)
        for word, count in insights['keywords'][:15]:
            print(f"  • {word}: {count}")

        if insights['recommendations']:
            print("\n" + "-" * 80)
            print("РЕКОМЕНДАЦИИ")
            print("-" * 80)
            for rec in insights['recommendations']:
                print(f"  • {rec}")

        print("\n" + "=" * 80)

    def create_content_plan(self, weeks: int = None, posts_per_week: int = None, instructions: str = ""):
        """Создание контент-плана"""
        print("\n" + "=" * 80)
        print("СОЗДАНИЕ КОНТЕНТ-ПЛАНА".center(80))
        print("=" * 80 + "\n")

        # Загружаем посты и создаем анализатор
        posts = self.collector.load_posts()
        if not posts:
            print("[!] Нет постов в базе данных")
            return

        self.analyzer = PostAnalyzer(posts)
        self.planner = ContentPlanner(self.analyzer)

        # Генерируем план
        content_plan = self.planner.generate_content_plan(
            weeks=weeks,
            posts_per_week=posts_per_week,
            additional_instructions=instructions
        )

        # Выводим и сохраняем
        self.planner.print_content_plan(content_plan)
        filename = self.planner.save_content_plan(content_plan)

        print(f"\n[OK] Контент-план сохранен в {filename}")

        return content_plan

    def index_posts(self):
        """Индексация постов для RAG"""
        print("\n" + "=" * 80)
        print("ИНДЕКСАЦИЯ ПОСТОВ ДЛЯ RAG".center(80))
        print("=" * 80 + "\n")

        posts = self.collector.load_posts()
        if not posts:
            print("[!] Нет постов в базе данных")
            return

        self.generator = RAGPostGenerator()
        self.generator.index_posts(posts)

        # Анализируем стиль
        style = self.generator.analyze_style(posts)
        print("\nСтиль канала:")
        print(f"  • Средняя длина: {style['avg_length']:.0f} символов")
        print(f"  • Эмодзи используют: {style['emoji_usage']:.0%} постов")
        print(f"  • Ссылки: {style['link_usage']:.0%} постов")
        print(f"  • Хештеги: {style['hashtag_usage']:.0%} постов")

        print(f"\n[OK] Посты проиндексированы для RAG генерации")

    def generate_posts(self, plan_file: str = None, output_file: str = None):
        """Генерация постов по контент-плану"""
        print("\n" + "=" * 80)
        print("ГЕНЕРАЦИЯ ПОСТОВ".center(80))
        print("=" * 80 + "\n")

        # Загружаем генератор
        self.generator = RAGPostGenerator()
        if not self.generator.load_collection():
            print("[!] Коллекция не найдена. Сначала проиндексируйте посты командой 'index'")
            return

        # Загружаем контент-план
        if not plan_file:
            # Ищем последний файл плана
            plan_files = sorted(Path("data").glob("content_plan_*.json"), reverse=True)
            if not plan_files:
                print("[!] Не найден файл контент-плана. Сначала создайте план командой 'plan'")
                return
            plan_file = str(plan_files[0])

        print(f"Загружаю контент-план из {plan_file}...")

        import json
        with open(plan_file, 'r', encoding='utf-8') as f:
            content_plan = json.load(f)

        # Генерируем посты
        if not output_file:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"data/generated_posts_{timestamp}.json"

        generated = self.generator.generate_posts_from_plan(
            content_plan=content_plan,
            save_to_file=output_file
        )

        # Выводим примеры
        print("\n" + "=" * 80)
        print("ПРИМЕРЫ СГЕНЕРИРОВАННЫХ ПОСТОВ".center(80))
        print("=" * 80)

        for post in generated[:3]:
            print(f"\nНеделя {post['week']}, {post['day']} {post['time']}")
            print(f"Тема: {post['topic']}")
            print("-" * 80)
            print(post['generated_text'])
            print("=" * 80)

        print(f"\n[OK] Сгенерировано {len(generated)} постов")
        print(f"[OK] Сохранено в {output_file}")

    async def full_pipeline(self, collect_limit: int = 100):
        """Полный пайплайн: сбор -> анализ -> план -> генерация"""
        print("\n" + "=" * 80)
        print("ПОЛНЫЙ ПАЙПЛАЙН CONTENT GENERATOR".center(80))
        print("=" * 80 + "\n")

        # 1. Сбор постов
        await self.collect_posts(limit=collect_limit)

        # 2. Анализ
        self.analyze_channel()

        # 3. Индексация для RAG
        self.index_posts()

        # 4. Создание плана
        content_plan = self.create_content_plan(weeks=2, posts_per_week=5)

        # 5. Генерация постов
        if content_plan:
            self.generate_posts()

        print("\n" + "=" * 80)
        print("ГОТОВО!".center(80))
        print("=" * 80)


def main():
    """Главная функция с CLI интерфейсом"""
    parser = argparse.ArgumentParser(
        description="Content Generator для Telegram каналов",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  # Полный пайплайн (все шаги)
  python main.py pipeline --limit 100

  # Сбор постов
  python main.py collect --limit 50

  # Анализ канала
  python main.py analyze

  # Создание контент-плана
  python main.py plan --weeks 4 --posts-per-week 7

  # Индексация для RAG
  python main.py index

  # Генерация постов
  python main.py generate

  # Генерация одного поста
  python main.py generate-one --topic "Утренняя мотивация"
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Команда для выполнения')

    # Команда: pipeline
    pipeline_parser = subparsers.add_parser('pipeline', help='Полный пайплайн')
    pipeline_parser.add_argument('--limit', type=int, default=100, help='Количество постов для сбора')

    # Команда: collect
    collect_parser = subparsers.add_parser('collect', help='Собрать посты из канала')
    collect_parser.add_argument('--limit', type=int, default=100, help='Количество постов')
    collect_parser.add_argument('--days', type=int, help='Собрать посты за последние N дней')

    # Команда: analyze
    subparsers.add_parser('analyze', help='Анализ канала')

    # Команда: plan
    plan_parser = subparsers.add_parser('plan', help='Создать контент-план')
    plan_parser.add_argument('--weeks', type=int, help='Количество недель')
    plan_parser.add_argument('--posts-per-week', type=int, help='Постов в неделю')
    plan_parser.add_argument('--instructions', type=str, default='', help='Дополнительные инструкции')

    # Команда: index
    subparsers.add_parser('index', help='Индексировать посты для RAG')

    # Команда: generate
    generate_parser = subparsers.add_parser('generate', help='Генерировать посты по плану')
    generate_parser.add_argument('--plan', type=str, help='Путь к файлу контент-плана')
    generate_parser.add_argument('--output', type=str, help='Путь для сохранения результата')

    # Команда: generate-one
    generate_one_parser = subparsers.add_parser('generate-one', help='Сгенерировать один пост')
    generate_one_parser.add_argument('--topic', type=str, required=True, help='Тема поста')
    generate_one_parser.add_argument('--format', type=str, default='text', help='Формат (text/photo/video)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    app = ContentGeneratorApp()

    try:
        if args.command == 'pipeline':
            asyncio.run(app.full_pipeline(collect_limit=args.limit))

        elif args.command == 'collect':
            asyncio.run(app.collect_posts(limit=args.limit, days_back=args.days))

        elif args.command == 'analyze':
            app.analyze_channel()

        elif args.command == 'plan':
            app.create_content_plan(
                weeks=args.weeks,
                posts_per_week=args.posts_per_week,
                instructions=args.instructions
            )

        elif args.command == 'index':
            app.index_posts()

        elif args.command == 'generate':
            app.generate_posts(plan_file=args.plan, output_file=args.output)

        elif args.command == 'generate-one':
            generator = RAGPostGenerator()
            if generator.load_collection():
                post = generator.generate_post(topic=args.topic, format_type=args.format)
                print("\n" + "=" * 80)
                print(post)
                print("=" * 80)

                while True:
                    print("\nВведите замечания для улучшения (или Enter чтобы принять, 'q' чтобы выйти):")
                    feedback = input("> ").strip()
                    if not feedback or feedback.lower() == 'q':
                        break
                    post = generator.refine_post(feedback)
                    print("\n" + "=" * 80)
                    print(post)
                    print("=" * 80)
            else:
                print("[!] Сначала проиндексируйте посты командой 'index'")

    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
