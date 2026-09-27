# ИИ-прогноз загрузки трамвайных маршрутов Москвы

Хакатон МТТЕХ. Почасовой прогноз посадок по 10 маршрутам трамвая на горизонт от дня до года и рабочее место диспетчера,
которое превращает прогноз в решения: где и когда ждать давки, сколько вагонов выпустить, что делать сейчас.

**Модель v7 — WAPE-score 0,88399 на лидерборде** (ноябрь–декабрь 2025).
Прогноз = уровень маршрута × форма дня (CatBoost + профиль) × сезонный множитель месяца; обучение на истории,
очищенной от перекрытий и сбоев.

## Быстрый старт

```bash
git clone https://github.com/dzorin350-cloud/mostransport-hakaton.git
cd mostransport-hakaton/service
docker compose up -d --build
```
Интерфейс — http://localhost:8080 (демо-аккаунт `demo` / `demo2025`), API и Swagger — http://localhost:8123/docs.
Что проверить — [docs/JURY.md](docs/JURY.md).

## Документы

| Раздел | Документ |
|---|---|
| Модель: артефакты, код обучения и инференса, запуск | [docs/MODEL.md](docs/MODEL.md) |
| Внешние данные | [docs/EXTERNAL_DATA.md](docs/EXTERNAL_DATA.md) |
| Веб-сервис: запуск, API, инструкция для жюри | [docs/JURY.md](docs/JURY.md), технические подробности — [service/README.md](service/README.md) |
| Архитектура, область применения и адаптации модели, зависимость от внешних данных | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Производительность и дополнительные возможности | [docs/PERFORMANCE_AND_FEATURES.md](docs/PERFORMANCE_AND_FEATURES.md) |
| Ограничения и план развития | [docs/LIMITATIONS_AND_ROADMAP.md](docs/LIMITATIONS_AND_ROADMAP.md) |
| Все прогоны и тесты | [docs/TESTS.md](docs/TESTS.md) |
| Дополнительно | [годовая модель и движок](docs/year_model_and_engine_report.md), [почему нет данных по остановкам и телематике](docs/TELEMATICS.md) |

## Структура репозитория

```
service/        веб-сервис: движок прогноза, API (FastAPI), интерфейс (React), Docker Compose
  engine/         применение модели, внешние данные, пересчёт; artifacts/ — 5 моделей CatBoost
  api/            API, авторизация, хранилище (PostgreSQL), нагрузочные тесты и их отчёты
  web/            интерфейс диспетчера
v7/             финальная модель: код обучения, отправленный сабмит и его md5
labels/         почасовые посадки январь–октябрь 2025 (исходные данные)
external/       внешние данные: календарь, сезонность data.mos.ru, ремонты Дептранса, погода
experiments/    журнал экспериментов (не рабочий код)
docs/           документы для жюри
Dockerfile      пакетный прогноз моделью v7 без сервиса
```
