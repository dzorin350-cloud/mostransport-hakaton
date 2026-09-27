# Архив исторических нагрузочных прогонов

`loadtest_legacy_20260927.zip` содержит прежние сырые CSV/логи Locust и
ресурсов, сохранённые перед очисткой `service/api/loadtest_report/`.
SHA-256 архива: `cf1f55f8d59c2ca958fbc2b5fcacdb60b4f8e30bede0df646bd800d2679bc312`.
Внутри ZIP пути начинаются с имени прогона или файла, как они лежали в
`service/api/loadtest_report/`.

Архив содержит 136 файлов: предварительные `ingest_proof_20260927_1/`,
`ingest_proof_20260927_2/`, `ingest_proof_20260927_pg/`, прежний ступенчатый
`steps_4cpu_main_0d8036a/` и ранние CSV Locust. Он заменяет их отдельные файлы
в рабочем дереве, не удаляя результаты из истории Git.

Итоговые доказательства оставлены без архивации:

- `service/api/loadtest_report/steps_4cpu_final_C1/` — ступенчатый тест итоговой модели;
- `service/api/loadtest_report/ingest_proof_merged_final/` — приём фактов и пересчёт под нагрузкой;
- `dispatcher_final_4cpu_210u_10m_*` — 10-минутный прогон;
- `dispatcher_cached_2cpu_100u_*` — режим 2 vCPU;
- `dispatcher_postgres_warm_4cpu_210u_*` — прогретый PostgreSQL.

Сводные таблицы и условия тестов — в `docs/TESTS.md`.
Новые локальные прогоны в `service/api/loadtest_report/` игнорируются Git;
если новый отчёт нужен для защиты, его можно добавить явно через `git add -f`.
