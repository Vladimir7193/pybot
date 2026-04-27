# RocketBot - Smart Money Concept Trading Bot

Торговый бот для Bybit с поддержкой Smart Money Concept (SMC) стратегии.

## 🚀 Быстрый старт

### 1. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 2. Настройка .env
Скопируйте `.env.example` в `.env` и заполните:
```env
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
BYBIT_TESTNET=false

TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

RISK_PER_TRADE=0.01
LEVERAGE=10
MAX_POSITIONS=3
```

### 3. Запуск

**Paper Trading (рекомендуется для начала):**
```bash
# Windows
start_bot_paper.bat

# Linux/Mac
python bot_paper.py
```

**Live Trading:**
```bash
# Windows
start_bot.bat

# Linux/Mac
python bot.py
```

## 📊 Режимы работы

### STRICT Mode (по умолчанию)
```python
# config.py
ENABLE_SMC = True
SMC_MODE = "STRICT"
```
- 🔥 Самые качественные сигналы
- ⚠️ Мало сигналов (0-2 в день)
- ✅ Все фильтры обязательны (BOS, Sweep, Premium/Discount, Entry Zone)

### RELAXED Mode
```python
# config.py
ENABLE_SMC = True
SMC_MODE = "RELAXED"
```
- ⚡ Больше сигналов (2-5 в день)
- ⚠️ Менее строгие фильтры
- ✅ Только Premium/Discount обязателен

### CLASSIC Mode
```python
# config.py
ENABLE_SMC = False
```
- 📊 Классическая стратегия (EMA + RSI + ATR)
- ⚠️ Без SMC фильтров

## 📚 Документация

- **QUICK_START_PAPER.md** - Инструкция по paper trading
- **SMC_QUICK_START.md** - Введение в SMC стратегию
- **SMC_STRICT_MODE_QUICK_START.md** - Детальное описание STRICT режима
- **READY_PATCH_NOTES.txt** - История изменений

## ⚙️ Конфигурация

Основные параметры в `config.py`:

```python
# Символы для торговли
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "MNTUSDT", "DOGEUSDT", "XAUUSDT"]

# Таймфреймы
HTF = "240"   # 4h - тренд
LTF = "15"    # 15m - вход
CTF = "D"     # Daily - контекст

# Риск-менеджмент
RISK_PER_TRADE = 0.01   # 1% на сделку
MAX_POSITIONS = 3       # Максимум открытых позиций
DD_WARNING = 0.10       # 10% просадка → снижение риска
DD_DANGER = 0.15        # 15% просадка → снижение риска

# SMC параметры
PREMIUM_DISCOUNT_THRESHOLD = 0.45  # Порог Premium/Discount зон
KEY_LEVEL_IMPORTANCE_MIN = 0.9     # Минимальная важность ключевых уровней
```

## 📈 Мониторинг

### Логи
```bash
# Последние 50 строк
tail -50 logs/rocketbot.log

# Следить в реальном времени
tail -f logs/rocketbot.log

# Искать ошибки
grep ERROR logs/rocketbot.log
```

### Telegram уведомления
Бот отправляет:
- 🤖 Старт/стоп бота
- 🚀 Сигналы на вход
- ✅ Закрытие позиций
- 🚨 Ошибки

### Статистика отклонений
В логах отображается статистика почему сигналы не генерируются:
```
📊 Tick rejects:  reject_htf_trend=3, reject_sweep=2, reject_pd_zone=1
📊 Daily rejects: reject_htf_trend=45, reject_range=23, reject_sweep=18
💡 Топ блокировка [reject_htf_trend=45]: рынок в боковике — норма, ждём структуру
```

## 🔧 Тестирование

```bash
# Тест SMC
python test_smc.py

# Тест strict mode
python test_strict_mode.py

# Сравнение режимов
python test_mode_comparison.py

# Полная интеграция
python test_integration_complete.py
```

## ⚠️ Важно

1. **Начните с paper trading** на 1-2 дня
2. **Проверьте логи** на отсутствие ошибок
3. **Мониторьте Telegram** уведомления
4. **Используйте testnet** для первых тестов
5. **Не рискуйте** больше 1% на сделку

## 🐛 Исправленные баги (20.04.2026)

✅ Исправлена ошибка `'tuple' object has no attribute 'get'`  
✅ Исправлена ошибка `name 'struct_bias' is not defined`  
✅ Добавлена обработка rate limit (HTTP 429)  
✅ Добавлена валидация типов данных от API  

Подробности в `READY_PATCH_NOTES.txt`

## 📞 Поддержка

При возникновении проблем:
1. Проверьте `logs/rocketbot.log`
2. Проверьте `.env` файл (API ключи)
3. Проверьте Telegram уведомления
4. Запустите тесты

## 📄 Лицензия

Proprietary - для личного использования

---

**Версия:** 1.0  
**Дата:** 20.04.2026  
**Статус:** ✅ Готов к использованию
