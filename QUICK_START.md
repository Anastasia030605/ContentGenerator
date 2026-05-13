# Быстрый старт (БЕСПЛАТНО)

## Вариант 1: Ollama (рекомендуется - полностью бесплатно)

### 1. Установите Ollama

Скачайте и установите с https://ollama.com/download

### 2. Запустите модель

Откройте новый терминал и выполните:

```bash
ollama pull llama3.2:3b
```

Это загрузит бесплатную модель (~2GB). Для русского языка лучше используйте:

```bash
ollama pull qwen2.5:3b
```

### 3. Настройте .env

Откройте `.env` и укажите:

```env
# Telegram (ОБЯЗАТЕЛЬНО)
TELEGRAM_API_ID=12345678            # Получить на https://my.telegram.org/apps
TELEGRAM_API_HASH=ваш_хэш
TELEGRAM_PHONE=+79991234567
TELEGRAM_CHANNEL_USERNAME=ваш_канал

# AI Provider
AI_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:3b
```

### 4. Запустите

```bash
python main.py pipeline --limit 20
```

---

## Вариант 2: Groq (бесплатный API)

### 1. Получите API ключ

1. Зарегистрируйтесь на https://console.groq.com/
2. Создайте API ключ в разделе Keys
3. **БЕСПЛАТНО**: 30 запросов в минуту

### 2. Настройте .env

```env
# Telegram (ОБЯЗАТЕЛЬНО)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=ваш_хэш
TELEGRAM_PHONE=+79991234567
TELEGRAM_CHANNEL_USERNAME=ваш_канал

# AI Provider
AI_PROVIDER=groq
GROQ_API_KEY=gsk-ваш-ключ-groq
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Запустите

```bash
python main.py pipeline --limit 20
```

---

## Доступные модели

### Ollama (локально):
- `llama3.2:3b` - быстрая, хорошая для англ (2GB)
- `qwen2.5:3b` - отлично понимает русский (2GB)
- `llama3.2:1b` - очень быстрая, базовая (1GB)
- `mistral:7b` - мощная, нужно больше RAM (4GB)

Выбрать модель: https://ollama.com/library

### Groq (API):
- `llama-3.3-70b-versatile` - самая мощная (рекомендуется)
- `llama-3.1-8b-instant` - быстрая
- `mixtral-8x7b-32768` - большой контекст

---

## Получение Telegram API credentials

1. Перейдите на https://my.telegram.org/apps
2. Войдите с номером телефона
3. Создайте приложение (любое название)
4. Скопируйте `api_id` и `api_hash` в `.env`

---

## Команды

```bash
# Полный пайплайн
python main.py pipeline --limit 50

# Только анализ
python main.py collect --limit 30
python main.py analyze

# Создание плана и генерация
python main.py plan --weeks 2
python main.py index
python main.py generate
```

---

## Troubleshooting

### Ollama не подключается
```bash
# Проверьте, что Ollama запущен
ollama list

# Если не запущен, скачайте модель
ollama pull qwen2.5:3b
```

### Ошибка "Collection not found"
```bash
# Сначала проиндексируйте посты
python main.py collect --limit 20
python main.py index
```

### Telegram просит код
При первом запуске Telegram отправит код в приложение - введите его в консоли.

---

**Готово!** Теперь у вас работает полностью бесплатный генератор контента для Telegram 🎉
