"""Офлайн-обучение моделей CatBoost для движка (в сервисе модели не обучаются, только применяются).

Использует ровно код итоговой модели (../../model/code): сборка сетки из labels/, очистка, 5 моделей CatBoost
с параметрами Optuna. Модели сохраняются в artifacts/ вместе с config.json.

    python -m service.engine.train        (из корня репозитория)
"""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; V7 = ROOT / "model" / "code"; ART = Path(__file__).resolve().parent / "artifacts"
subprocess.run([sys.executable, str(V7 / "build_grid.py")], check=True, cwd=V7)
sys.path.insert(0, str(V7))
from clean import G, clean_grid, fit_cb, best, ROUTES     # noqa: E402  (код итоговой модели)
tr, flags = clean_grid(G.copy(), 1.5, protect_weeks=0)
ART.mkdir(exist_ok=True)
names = []
for s in range(5):
    m = fit_cb(tr, best, s); f = f"catboost_seed{s}.cbm"; m.save_model(str(ART / f)); names.append(f)
cfg = {"model_version": "Итоговая модель (CatBoost x5 + профиль + сезонный множитель; лидерборд 0.88399) + годовая форма дня",
       "trained_on_until": str(tr.date.max().date()), "trained_on_rows": int(len(tr)), "cleaned_route_days": int(flags.m.sum()),
       "routes_all": [1, 5, 7, 11, 12, 17, 25, 26, 28, 50], "routes_model": [int(r) for r in ROUTES],
       "models": names, "params": {k: best[k] for k in ("lvl", "weeks", "norm_win", "iters", "depth", "lr", "l2", "rs", "ss", "loss", "boot")}}
(ART / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
print("сохранено:", names, "| обучено до", cfg["trained_on_until"])
