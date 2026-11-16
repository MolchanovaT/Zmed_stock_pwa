# Деплой клинических модулей на прод

Раскатка `clinic_reports` (отчёты об операциях) и `clinic_stock` (учёт на ОХ)
на прод-сервер `root@93.183.83.82`, `/root/zmed_pwa/`.

Файл — боевой чек-лист: иди сверху вниз, каждый шаг — одна короткая команда
(так в WSL/PowerShell не ломаются). Не прыгай вперёд, пока текущий шаг не дал
ожидаемый результат.

---

## 0. Предполётное (локально, до начала деплоя)

1. В Git должно быть чисто:
   ```
   git status
   ```
   Ожидание: `nothing to commit, working tree clean`.

2. Запомни текущий прод-коммит (для rollback). Получим его на шаге 1.

3. Пересобери фронт в PowerShell (в WSL rollup-нативный пакет не встаёт):
   ```
   cd frontend
   npm run build
   ```
   Должно обновиться `frontend/dist/assets/index-<hash>.js`.

4. Закоммить `dist/` и запушь:
   ```
   git add frontend/dist
   git commit -m "build(frontend): rebuild dist перед деплоем клинических модулей"
   git push
   ```

---

## 1. На проде: забрать код

```
ssh root@93.183.83.82
cd /root/zmed_pwa
git log --oneline -1
```
Запиши ID (это точка rollback'а).

```
git status
```
Ожидание: `nothing to commit, working tree clean`. Если нет — разбираться
вручную (на проде могут быть локальные правки `.env` вне git, это норма; но
правок кода быть не должно).

```
git pull
git log --oneline -1
```
Ожидание: `03abc21` или новее.

---

## 2. Бэкап прод-БД (обязательно перед миграциями)

```
cp /root/zmed_pwa/data/implant_stock.db /root/zmed_pwa/data/implant_stock.db.bak.$(date +%Y%m%d-%H%M)
ls -lh /root/zmed_pwa/data/implant_stock.db*
```
Должен появиться файл `.bak.YYYYMMDD-HHMM`. **Не удалять его минимум неделю.**

---

## 3. Миграции схемы (идемпотентные, безопасно перезапускать)

Все скрипты в `scripts/` работают с `CREATE TABLE IF NOT EXISTS` — повторный
запуск ничего не сломает. Порядок:

```
cd /root/zmed_pwa
python3 scripts/09_create_organizations.py
```
Ожидание: `Готово` (или `уже существует`), без трейсбэка.

```
python3 scripts/10_create_operation_reports.py
python3 scripts/11_create_clinic_stock.py
python3 scripts/13_create_operation_report_audit.py
python3 scripts/14_create_otp_codes.py
python3 scripts/15_create_report_tags.py
python3 scripts/16_create_fts_reports.py
```
Каждый — отдельной командой (не через `&&`). После каждого — глазами проверь,
что нет ошибок.

Проверка — что все таблицы на месте:
```
sqlite3 /root/zmed_pwa/data/implant_stock.db ".tables"
```
В выводе должны быть: `organizations`, `operation_reports`,
`operation_report_files`, `operation_report_audit`, `operation_report_tags`,
`report_tags`, `operation_reports_fts`, `otp_codes`, `clinic_stock_locations`,
`clinic_stock_items`, `clinic_stock_balances`, `clinic_stock_movements`.

---

## 4. Alembic baseline (ОДИН РАЗ на этой БД)

Проверка:
```
cd /root/zmed_pwa
alembic current
```
Если вывод пустой — ставим baseline:
```
alembic stamp 0001
alembic current
```
Должно вывести `0001 (head)`. Если `0001 (head)` уже было в первом `current` —
шаг не нужен.

---

## 5. Папка под файлы отчётов

```
mkdir -p /root/zmed_pwa/data/reports
ls -ld /root/zmed_pwa/data/reports
```
Владелец должен совпадать с владельцем `/root/zmed_pwa/data/` (чтобы контейнер
через bind-mount мог писать). Если нет — `chown` под того же пользователя.

---

## 6. Правки прод-`.env`

```
nano /root/zmed_pwa/.env
```

Добавить (если ещё нет) следующие строки — каждая на своей:

```
REPORTS_DIR=/root/zmed_pwa/data/reports
PWA_BASE_URL=https://<реальный домен PWA>
CLINIC_SILENCE_DAYS=14
```

**Не добавлять** `OTP_REQUIRED_FOR_SUBMIT=1` — включим позже, когда юристы
скажут, что подпись отчёта должна быть двухфакторной. Пока отчёт
подтверждается просто нажатием «Отправить».

Выйти из nano: `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## 7. Рестарт контейнеров

Три контейнера, которые видят новый код:

**7.1. FastAPI (PWA-бэкенд + раздаёт фронт-dist)**
```
docker restart stockbot2_implants_api
docker logs --tail 50 stockbot2_implants_api
```
В логах ждать `Uvicorn running on http://0.0.0.0:8000`. Трейсбэков быть не
должно.

**7.2. Scheduler (для `clinic_silence_check` пн-пт 10:00 МСК)**
```
docker restart stockbot2_implants_trash_scheduler
docker logs --tail 30 stockbot2_implants_trash_scheduler
```
В логах ждать `🕒 Планировщик запущен`.

**7.3. Flask-админка `:5102`** (для роутов `/organizations`,
`/admin-clinic-reports`, `/admin-audit-log`, `/report-tags`)

Контейнер зовётся криво после G3-инцидента — найди его сам:
```
docker ps --format '{{.Names}}' | grep -E 'trash_bot|5102'
```
Увидишь что-то вроде `e3dd5933f484_stockbot2_implants_trash_bot` или
`stockbot2_implants_trash_bot`. Подставь это имя:
```
docker restart <имя-из-предыдущей-команды>
```

---

## 8. Smoke-тест

**8.1. Таблицы на месте:**
```
sqlite3 /root/zmed_pwa/data/implant_stock.db ".tables" | tr ' ' '\n' | grep -c "operation_report\|clinic_stock\|organizations\|otp_codes\|report_tags"
```
Ожидание: `9` или больше.

**8.2. API отвечает (401 без токена — это ожидаемо):**
```
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/clinic-reports
```
Ожидание: `401`.

**8.3. В браузере, залогинься как `admin` в PWA.**
На главной должны появиться две новые плитки:
- 📋 Отчёты клиник
- 📦 Учёт ОХ

(Плитки появятся только если у `admin` в `modules` включены `clinic_reports` и
`clinic_stock` — см. шаг 9).

**8.4. Админка `:5102`**, залогинься как супер (`admin` / `molchanova`).
В шапке навигации должны быть кнопки:
- 🏥 Организации
- 📋 Отчёты клиник

---

## 9. Включить модули у ZMed-сотрудников

Админка `:5102` → **Пользователи**.

У каждого сотрудника ZMed, которому нужен доступ к клиническим данным,
в столбце «Модули» поставь галки:
- ☑ clinic_reports
- ☑ clinic_stock

SQL-проверка кандидатов (кого смотреть):
```
sqlite3 /root/zmed_pwa/data/implant_stock.db "SELECT id, username, modules FROM users WHERE username IS NOT NULL;"
```
У кого в `modules` уже есть `implants` — тем же почти наверняка нужны и клиники.

---

## 10. Завести первую клинику-пилот

Админка `:5102`:

1. **Организации** → «+ Новая» → `kind=clinic`, имя клиники, опционально ИНН.
2. **Пользователи** → «+ Новый»:
   - `username` / `password` — для входа в PWA
   - `email` — для OTP-подписи и копий писем
   - `organization` = только что созданная клиника
   - `modules`: ☑ clinic_reports, ☑ clinic_stock (больше ничего)
   - `is_superuser` — **снять** (клиника не должна видеть админку)
3. Отправь клинике письмо-приглашение (шаблон будет отдельно, см.
   `docs/CLINIC_ONBOARDING.md`).

---

## 11. Если что-то пошло не так — rollback

**Код — к старому коммиту:**
```
cd /root/zmed_pwa
git log --oneline -5
git checkout <ID-коммита-из-шага-1>
docker restart stockbot2_implants_api
docker restart stockbot2_implants_trash_scheduler
docker restart <имя-админки>
```

**БД — к бэкапу:**
```
docker stop stockbot2_implants_api
docker stop stockbot2_implants_trash_scheduler
cp /root/zmed_pwa/data/implant_stock.db.bak.<TIMESTAMP> /root/zmed_pwa/data/implant_stock.db
docker start stockbot2_implants_api
docker start stockbot2_implants_trash_scheduler
```

Пустые клинические таблицы старому коду не мешают — даже если БД не откатить,
старая версия просто не знает про них.

---

## 12. После деплоя: за чем следить первую неделю

- `docker logs --tail 100 stockbot2_implants_api` — трейсбэки на эндпоинтах
  `/api/clinic-*`;
- `docker logs --tail 100 stockbot2_implants_trash_scheduler` — что
  `clinic_silence_check` отработала в пн-пт 10:00 МСК;
- `ls -lh /root/zmed_pwa/data/reports/` — файлы создаются, сюда должны
  добавляться новые при аплоаде;
- `sqlite3 /root/zmed_pwa/data/implant_stock.db "SELECT COUNT(*) FROM operation_reports;"`
  и `SELECT COUNT(*) FROM clinic_stock_movements;` — цифры должны расти.
