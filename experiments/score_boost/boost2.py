"""Прогноз итоговой модели на фолд с разложением на части — для проверки поправок уровня, сезонности и формы."""
import numpy as np, pandas as pd
import harness, clean
from harness import cb_share, fold_data, build_x, BASE_FEATS, ORDER
from clean import best, seas, cal, wape, dtype, FOLDS
P = clean.P
CLEAN = dict(thr=1.5, protect_weeks=0)
SETS = [BASE_FEATS, BASE_FEATS + ['daylen']]

def fold_pred(fold, seasfn=seas, seeds=2):
    """b: тестовые строки с признаками, pred — прогноз итоговой модели; tr — очищенная история до начала фолда"""
    p = dict(best); tr, te = fold_data(fold, CLEAN); o = tr.date.max()
    b = te.merge(build_x(te.date.unique()), on='date')
    months = sorted(te.date.dt.month.unique()); fac = seasfn(o, months); f = b.date.dt.month.map(fac).values
    sh = np.mean([np.mean([cb_share(fold, CLEAN, list(v), ['route'], p, s) for v in SETS], axis=0) for s in range(seeds)], axis=0)
    L = tr[tr.date > o - pd.Timedelta(days=56)].groupby('route').boardings.sum() / 56
    t = tr[tr.date > o - pd.Timedelta(weeks=4)].merge(cal(tr.date.unique()), on='date'); t = t[t.hol_wd == 0]
    PR = t.groupby(['route','dow','hour']).boardings.median().rename('pp').reset_index()
    pf = b.merge(PR, on=['route','dow','hour'], how='left').pp.fillna(0).values * f
    cb = sh * b.route.map(L).values * f
    w = np.where(b.dow.values >= 5, 0.8, 0.6)
    b['pred'] = np.where(b.hol_wd.values == 1, cb, w * cb + (1 - w) * pf)
    b['f'] = f; b['L'] = b.route.map(L).values; b['dt'] = dtype(b.date)
    return b, tr

def score(b, col='pred'): return 1 - wape(b.boardings.values, b[col].values)

def show(name, res, folds=ORDER):
    m = np.mean([res[x] for x in folds])
    print(f"{name:<62} " + "  ".join(f"{x}:{res.get(x, float('nan')):.4f}" for x in folds) + f"  | mean {m:.4f}", flush=True)
    return m
