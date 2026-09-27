"""Офлайн-обучение моделей CatBoost для движка (в сервисе модели не обучаются, только применяются).

Использует ровно код итоговой модели (../../model/code): сборка сетки из labels/, очистка, по 5 моделей CatBoost
на каждый набор признаков формы дня (базовый и с длиной светового дня) с параметрами Optuna.
Модели сохраняются в artifacts/ вместе с config.json.

    python -m service.engine.train        (из корня репозитория)
"""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; MODEL = ROOT / "model" / "code"; ART = Path(__file__).resolve().parent / "artifacts"
subprocess.run([sys.executable, str(MODEL / "build_grid.py")], check=True, cwd=MODEL)
sys.path.insert(0, str(MODEL))
from clean import G, clean_grid, fit_cb, best, ROUTES     # noqa: E402  (код итоговой модели)
tr, flags = clean_grid(G.copy(), 1.5, protect_weeks=0)
ART.mkdir(exist_ok=True)
sets = []
for fs in best["shape_sets"]:
    tag = "_daylen" if "daylen" in fs else ""
    names = []
    for s in range(5):
        m = fit_cb(tr, best, s, fs); f = f"catboost{tag}_seed{s}.cbm"; m.save_model(str(ART / f)); names.append(f)
    sets.append({"feats": fs, "models": names})
cfg = {"model_version": "Итоговая модель (CatBoost x10: форма дня + длина светового дня; профиль; сезонность маршрута; лидерборд 0.88960) + годовая форма дня",
       "trained_on_until": str(tr.date.max().date()), "trained_on_rows": int(len(tr)), "cleaned_route_days": int(flags.m.sum()),
       "routes_all": [1, 5, 7, 11, 12, 17, 25, 26, 28, 50], "routes_model": [int(r) for r in ROUTES],
       "model_sets": sets,
       "params": {k: best[k] for k in ("lvl", "weeks", "prof_agg", "route_season_lambda", "norm_win", "iters", "depth", "lr", "l2", "rs", "ss", "loss", "boot")}}
(ART / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
print("сохранено:", [x["models"] for x in sets], "| обучено до", cfg["trained_on_until"])
