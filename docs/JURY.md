# Инструкция для жюри

ИИ-прогноз загрузки трамвайных маршрутов Москвы: почасовой прогноз посадок по маршрутам на горизонт от одного дня до года,
веб-сервис с картой, REST API и экспортом. WAPE-score на лидерборде — **0,88399**.

## Запуск (≈ 2 минуты)

Нужен Docker с Docker Compose и доступ в интернет (сервис сам скачивает календарь и сезонность).

```bash
git clone <ссылка на репозиторий> && cd mostransport-hakaton/service
docker compose up -d --build
```

- Дашборд: **http://localhost:8080** — сначала откроется окно входа: вкладка «Регистрация», любой логин (латиница, от 3 символов) и пароль (от 6 символов).
- API: **http://localhost:8123**, интерактивная документация (Swagger): **http://localhost:8123/docs**.
- Первый запуск: сервис ~30 с строит прогноз (применяет модель и скачивает внешние данные), затем `docker compose ps` показывает `healthy`.
- Минимальная конфигурация по ТЗ (2 vCPU / 2 ГБ): `docker compose -f docker-compose.yml -f docker-compose.2cpu.yml up -d --build`.
- Остановить: `docker compose down` (с удалением пользователей и принятых данных: `docker compose down -v`).

## Что проверить за 5 минут

1. **Дашборд:** вход → карта маршрутов, графики по часам и маршрутам, KPI. Кнопки «День / Месяц / Год» — три горизонта прогноза.
2. **Корректирующие коэффициенты:** ползунок и кнопки «Дождь» (×0,96, измеренный эффект дождливого дня) / «Событие» — прогноз меняется сразу.
3. **Экспорт:** кнопки CSV / XLSX внизу правой панели.
4. **Как построен прогноз:** `GET /model/info` — дата последних данных, горизонт, сезонные множители, откуда взяты внешние данные.
5. **Погода (демо):** стенд работает на данных до 31.10.2025, поэтому поправка на дождь показана в демо-режиме — по фактической
   погоде архива за 1–16 ноября (сильный дождь 12 и 15 ноября → прогноз на 2,5 % ниже). В проде — прогноз погоды на 16 дней; в сабмите погоды нет.
6. **Приём новых данных:** `POST /ingest/validations` (сырые валидации) — через ~1 минуту дата данных и горизонт сдвигаются сами.

## API через curl

```bash
B=http://localhost:8123
curl -X POST $B/auth/register -H 'Content-Type: application/json' -d '{"username":"jury","password":"jury123"}'
TOKEN=$(curl -s -X POST $B/auth/token -d 'username=jury&password=jury123' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"

curl -H "$H" "$B/model/info"                                                                  # как построен прогноз
curl -H "$H" "$B/forecast?date_from=2025-11-12&date_to=2025-11-12&route=17"                   # день по часам
curl -H "$H" "$B/forecast?date_from=2025-11-01&date_to=2025-11-30&granularity=day"            # месяц по дням
curl -H "$H" "$B/forecast?date_from=2025-11-01&date_to=2026-10-31&granularity=month&route=17" # год по месяцам
curl -H "$H" "$B/forecast?date_from=2025-11-10&date_to=2025-11-16&granularity=week&coefficient=0.96"
curl -H "$H" -o forecast.xlsx "$B/forecast/export?date_from=2025-11-01&date_to=2025-11-07&fmt=xlsx"
curl -H "$H" "$B/forecast/stops?date_from=2025-11-12&date_to=2025-11-12&route=17&hour_from=7&hour_to=9"  # по остановкам
curl -H "$H" "$B/forecast?date_from=2027-01-01&date_to=2027-01-02"                            # вне горизонта → понятная ошибка
```

| Эндпоинт | Назначение |
|---|---|
| `POST /auth/register`, `POST /auth/token`, `GET /auth/me` | регистрация, вход (OAuth2 Password Flow → JWT), текущий пользователь |
| `GET /forecast` | прогноз: `date_from`, `date_to`, `route` (можно несколько), `hour_from`/`hour_to`, `granularity=hour\|day\|week\|month`, `coefficient` |
| `GET /forecast/export` | то же в файл `fmt=csv\|xlsx` |
| `GET /model/info` | дата данных, горизонт, множители, источники внешних данных и их статус |
| `POST /ingest/hourly` | почасовые посадки CSV `route;date;hour;boardings` |
| `POST /ingest/validations` | сырые валидации в формате `train.csv`, агрегация на стороне сервиса |
| `GET /stops`, `GET /forecast/stops` | остановки и прогноз по остановкам (оценочная разбивка по расписанию GTFS) |
| `GET /routes`, `GET /routes/geometry` | маршруты и их геометрия (OpenStreetMap) |
| `GET /health`, `GET /metrics` | состояние сервиса (без авторизации) |

## Ссылки для формы «Загрузка решения»

| Поле формы | Где в репозитории |
|---|---|
| Артефакты ML-модели, код обучения/инференса, README | `v7/` (финальная модель, воспроизводит сабмит байт в байт), `service/engine/` (инференс в сервисе, `artifacts/` — модели CatBoost, `train.py` — обучение), [README.md](../README.md) |
| Внешние данные | [docs/EXTERNAL_DATA.md](EXTERNAL_DATA.md), данные — `external/`, `service/engine/fallback/` |
| Веб-сервис (Docker), точки входа API, инструкция | этот файл, [service/README.md](../service/README.md) |
| Схема архитектуры, область определения и адаптации, зависимость от внешних данных | [ARCHITECTURE.md](../ARCHITECTURE.md), [service/engine/README.md](../service/engine/README.md), [docs/APPLICABILITY.md](APPLICABILITY.md), [docs/EXTERNAL_DATA.md](EXTERNAL_DATA.md) |
| Производительность, дополнительные возможности | [docs/TESTS.md](TESTS.md) §5, [service/README.md](../service/README.md) «Производительность», дополнительные возможности — [docs/ЗАМЕТКА_развитие_и_доп_возможности.md](ЗАМЕТКА_развитие_и_доп_возможности.md) |
| Ограничения и план развития | [docs/APPLICABILITY.md](APPLICABILITY.md) «Ограничения», [docs/ЗАМЕТКА_развитие_и_доп_возможности.md](ЗАМЕТКА_развитие_и_доп_возможности.md) |

Все прогоны и тесты (качество модели, календарь, погода, движок, авторизация, приём данных, нагрузка) — [docs/TESTS.md](TESTS.md).
