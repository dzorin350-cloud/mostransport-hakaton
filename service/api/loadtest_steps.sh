#!/bin/bash
# Ступенчатый нагрузочный тест: смешанный профиль диспетчера (loadtest_dispatcher.py) на запущенном сервисе.
# Запуск из корня репозитория при поднятом `cd service && docker compose up -d --build`:
#   OUT=service/api/loadtest_report/steps_run1 bash service/api/loadtest_steps.sh
#   python3 service/api/loadtest_steps_report.py service/api/loadtest_report/steps_run1
# Нужен Locust (pip install locust). Ступени: STEPS="25 50 100 ..." ; хост: HOST=http://127.0.0.1:8123
OUT=${OUT:?укажите OUT — папку для результатов}; mkdir -p "$OUT"
PY=${PYTHON:-python3}; HOST=${HOST:-http://127.0.0.1:8123}; CONTAINER=${CONTAINER:-service-api-1}
for U in ${STEPS:-25 50 100 150 200 300 400 600 800 1000 1300 1600}; do
  R=$(( U / 5 )); [ $R -lt 5 ] && R=5
  ( while true; do docker stats --no-stream --format '{{.CPUPerc}};{{.MemUsage}}' "$CONTAINER" >> "$OUT/res_$U.txt"; done ) &
  SAMPLER=$!
  $PY -m locust -f service/api/loadtest_dispatcher.py --host "$HOST" --headless -u $U -r $R \
      --run-time 75s --reset-stats --processes 4 --csv "$OUT/u$U" --only-summary > "$OUT/u$U.log" 2>&1
  kill $SAMPLER; wait $SAMPLER 2>/dev/null
  echo "ступень $U готова"; sleep 10
done
