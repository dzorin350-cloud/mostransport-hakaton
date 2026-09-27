# Веб-сервис и модель

Сервис применяет итоговую модель (**WAPE-score 0,89136** на лидерборде) к истории посадок, сам скачивает внешние данные
и отдаёт прогноз и функции диспетчера через API и интерфейс. Общая схема — [ARCHITECTURE.md](../ARCHITECTURE.md),
инструкция для жюри — [docs/JURY.md](../docs/JURY.md).

## Модель: артефакты, обучение, прогноз

Прогноз = уровень маршрута × форма дня × сезонный множитель. Форму дня дают 10 моделей CatBoost (5 базовых и 5 с длиной
светового дня) в смеси с профилем маршрута. Подробно — [docs/MODEL.md](../docs/MODEL.md).

| Что | Где |
|---|---|
| Обученные модели и параметры | [`engine/artifacts/`](engine/artifacts/): `catboost_seed*.cbm`, `catboost_daylen_seed*.cbm`, `config.json` |
| Код обучения | [`../model/code/`](../model/code/); модели для сервиса — [`engine/train.py`](engine/train.py) |
| Код прогноза в сервисе | [`engine/core.py`](engine/core.py) — применение модели, [`engine/sources.py`](engine/sources.py) — внешние данные, [`engine/refresher.py`](engine/refresher.py) — пересчёт |
| Прогноз без сервиса | [`../model/code/forecast.py`](../model/code/forecast.py) |
| Отправленный сабмит | [`../model/submission.csv`](../model/submission.csv) и его md5 |

```bash
# из корня репозитория
cd model/code && python build_grid.py && python final.py     # воспроизвести сабмит байт в байт
python forecast.py --start 2025-11-01 --end 2026-10-31         # прогноз на любой период до 12 месяцев
cd ../.. && python -m service.engine.train                      # переобучить модели сервиса
```

Зависимости модели — [`../requirements.txt`](../requirements.txt); то же в Docker: `docker build -t tram-model . && docker run --rm tram-model`.

## Запуск

```bash
cd service
docker compose up -d --build                                              # 4 vCPU / 4 ГБ
docker compose -f docker-compose.yml -f docker-compose.2cpu.yml up -d --build   # 2 vCPU / 2 ГБ
```

Интерфейс — http://127.0.0.1:8080 (вход `demo` / `demo2025`), API — http://127.0.0.1:8123, Swagger — http://127.0.0.1:8123/docs.
Остановить — `docker compose down`.

## Как работает

- **Движок** ([`engine/`](engine/README.md)) — фоновый процесс в контейнере `api`. Читает историю, скачивает календарь,
  статистику и прогноз погоды, строит прогноз на 12 месяцев. Пересчитывает его при появлении новых данных и раз в сутки.
- **Версии прогноза.** Каждый пересчёт записывается отдельной версией и становится текущим одной атомарной заменой.
  Воркеры API подхватывают новую версию без перезапуска. Старые версии остаются в архиве, по ним считается точность.
- **API** держит прогноз в памяти и отвечает за миллисекунды. Число воркеров равно числу vCPU.
- **Надёжность.** Если упал движок или API, контейнер перезапускается, прогноз сохраняется на томе `state`.
  Если недоступен внешний источник, используется кэш или встроенная копия.

## API

Все запросы, кроме `/health`, `/ready`, `/metrics` и `/docs`, требуют токен: `POST /auth/token` → заголовок
`Authorization: Bearer <токен>`. Ошибки возвращаются с понятным текстом на русском. Полный список с параметрами —
в Swagger, примеры — в [docs/JURY.md](../docs/JURY.md).

| Группа | Запросы |
|---|---|
| Доступ | `POST /auth/register`, `POST /auth/token`, `GET /auth/me` |
| Прогноз | `GET /forecast`, `GET /forecast/export`, `GET /forecast/stops`, `GET /stops`, `GET /routes/geometry` |
| Диспетчер | `GET /now`, `GET /alerts`, `GET /fleet`, `GET /plan`, `GET /plan/export`, `POST /decisions`, `GET /decisions/report` |
| Данные и качество | `POST /ingest/hourly`, `POST /ingest/validations`, `GET /monitor/accuracy`, `GET /model/info` |

**Приём данных.** Принимаются только даты после последней даты данных, полными днями, до 10 МБ за запрос. Повтор того же
пакета безопасен, пересекающиеся данные и неизвестные маршруты отклоняются. Новые данные подхватываются примерно за минуту.

**Хранилище.** Пользователи, журнал решений и журнал приёма — в PostgreSQL (контейнер `db`). Прогноз и архив — файлы Parquet
на томе `state`. Пароль базы по умолчанию годится только для локального демо: в проде задайте `TRAM_DB_PASSWORD` и `AUTH_SECRET`.

## Интерфейс

React-приложение в [`web/`](web/), карта на MapLibre, геометрия маршрутов из OpenStreetMap. Разделы: обзор, оперативная
ситуация, карта и остановки, загрузка вагонов, план выпуска, качество прогноза, журнал решений.

## Производительность

При обычном трафике (200–400 запросов в секунду) p95 — 5 мс; требование p95 ≤ 300 мс выдерживается до 1 100–1 430
запросов в секунду. Подробно — [docs/PERFORMANCE_AND_FEATURES.md](../docs/PERFORMANCE_AND_FEATURES.md).
Повторить тест: `api/loadtest_steps.sh`.

## Файлы

```
service/
├── docker-compose.yml         api + web + db
├── docker-compose.2cpu.yml    конфигурация 2 vCPU / 2 ГБ
├── engine/                    движок прогноза, обученные модели, встроенные копии данных
├── api/                       API, авторизация, хранилище, тесты, нагрузочные тесты
├── web/                       интерфейс
└── data/routes.geojson        геометрия маршрутов
```
