#!/bin/bash
S=/private/tmp/claude-501/-Users-denis-Documents-----------------------------/010cb3cc-d4d5-4cc0-bfa4-a45169a45c88/scratchpad; R=$S/repo
cd $R/service && docker compose -f docker-compose.yml -f $S/ov_stream.yml down >/dev/null 2>&1; docker volume rm service_stream_ingest >/dev/null 2>&1
docker compose -f docker-compose.yml -f $S/ov_stream.yml up -d --build --force-recreate >/dev/null 2>&1; for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' service-api-1)" = healthy ] && break; sleep 3; done
B=localhost:8123; TOKEN=$(curl -s -X POST $B/auth/token -d 'username=demo&password=demo2025' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])'); H="Authorization: Bearer $TOKEN"
echo "старт: $(curl -s $B/health)"
for n in w1 w2 w3 w4; do
  prev=$(curl -s $B/health | python3 -c "import json,sys;print(json.load(sys.stdin)['data_until'])")
  curl -s -X POST -H "$H" -H 'Content-Type: text/csv' --data-binary @$S/oct_$n.csv $B/ingest/hourly | python3 -c "import json,sys; d=json.load(sys.stdin); print('$n: принято строк',d.get('принято_строк',d))"
  for i in $(seq 1 60); do sleep 3; ok=$(for j in 1 2 3 4 5 6; do curl -s $B/health | python3 -c "import json,sys;print(json.load(sys.stdin)['data_until'])"; done | sort -u); [ "$ok" != "$prev" ] && [ $(echo "$ok" | wc -l) = 1 ] && break; done
  echo "   данные до $ok | $(curl -s -H "$H" $B/model/info | python3 -c "import json,sys; d=json.load(sys.stdin); print('пересчёт ok:',d['last_refresh']['ok'],'| база множителей',d['multiplier_base_month'],'| городская статистика до',d['sources']['ridership']['last_month_used'])")"
done
for mode in latest earliest; do curl -s -H "$H" "$B/monitor/accuracy?forecast=$mode" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('$mode: WAPE-score',d['wape_score'],'| часов',d['hours'],'| в среднем',d['mean_days_ahead'],'дн. до факта')
print('   по маршрутам:',[(r['route'],r['wape_score']) for r in d['by_route']])"; done
curl -s -H "$H" "$B/monitor/accuracy?forecast=latest" | python3 -c "
import json,sys,collections; d=json.load(sys.stdin); g=collections.defaultdict(list)
for x in d['by_day']: g[x['forecast_made_from_data_until']].append(x['wape_score'])
print('по версиям прогноза (latest):',{k:(len(v),round(sum(v)/len(v),4)) for k,v in sorted(g.items())})"
