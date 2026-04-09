# Stock-Bot

Telegram-бот для просмотра остатков оборудования по складам.

## Быстрый запуск (SQLite)
```bash
cp .env.example .env
pip install -r requirements.txt
python app/tools/import_csv.py stock.csv        # загрузите свой CSV
python -m app.bot.main
