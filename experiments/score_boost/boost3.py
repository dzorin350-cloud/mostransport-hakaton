"""Раунд 3: веса смеси и профиль, настройка β (сжатие и способ оценки), число seed — поверх итоговой модели C1."""
import numpy as np, pandas as pd, itertools
import clean
from harness import cb_share, fold_data, build_x, BASE_FEATS, ORDER
from clean import best, seas, cal, wape
P = clean.P; CLEAN = dict(thr=1.5, protect_weeks=0); SETS = [BASE_FEATS, BASE_FEATS + ['daylen']]

def beta_v(tr, weekdays_only=False, excl_jan=False):
    o = tr.date.max(); M = o.month
    t = tr
    if weekdays_only:
        c = cal(tr.date.unique()); t = tr.merge(c[['date','off']], on='date'); t = t[t.off == 0]
    d = t.groupby(['route', t.date.dt.month]).agg(s=('boardings','sum'), n=('date','nunique')).reset_index()
    full = tr.groupby(tr.date.dt.month).date.nunique(); d = d[d.date.map(full) >= 20]
    d['pd'] = d.s / d.n; out = {}
    for r, g in d.groupby('route'):
        g = g.set_index('date')
        if M not in g.index: continue
        ms = [m for m in g.index if m != M and not (excl_jan and m == 1)]
        if len(ms) < 2: continue
        y = np.log(g.loc[ms,'pd'] / g.loc[M,'pd']).values
        x = np.log(np.array([P.loc[2025, m] / P.loc[2025, M] for m in ms]))
        out[r] = float((x * y).sum() / (x * x).sum())
    return out

_comp = {}
def comp(fold, seeds=2, weeks=4, agg='median'):
    k = (fold, seeds, weeks, agg)
    if k in _comp: return _comp[k]
    p = dict(best); tr, te = fold_data(fold, CLEAN); o = tr.date.max()
    b = te.merge(build_x(te.date.unique()), on='date')
    fac = seas(o, sorted(te.date.dt.month.unique())); b['f'] = b.date.dt.month.map(fac).values
    sh = np.mean([np.mean([cb_share(fold, CLEAN, list(v), ['route'], p, s) for v in SETS], axis=0) for s in range(seeds)], axis=0)
    L = tr[tr.date > o - pd.Timedelta(days=56)].groupby('route').boardings.sum() / 56
    t = tr[tr.date > o - pd.Timedelta(weeks=weeks)].merge(cal(tr.date.unique()), on='date'); t = t[t.hol_wd == 0]
    PR = t.groupby(['route','dow','hour']).boardings.agg(agg).rename('pp').reset_index()
    b['pf'] = b.merge(PR, on=['route','dow','hour'], how='left').pp.fillna(0).values * b.f.values
    b['cb'] = sh * b.route.map(L).values * b.f.values
    _comp[k] = (b, tr); return b, tr

def predict(fold, w_wd=0.6, w_we=0.8, lam=0.5, bmode=(False, False), seeds=2, weeks=4, agg='median', w_hol=1.0):
    b, tr = comp(fold, seeds, weeks, agg)
    w = np.where(b.dow.values >= 5, w_we, w_wd); w = np.where(b.hol_wd.values == 1, w_hol, w)
    pred = w * b.cb.values + (1 - w) * b.pf.values
    bt = beta_v(tr, *bmode)
    kr = b.f.values ** (lam * (b.route.map(bt).fillna(1.0).values - 1))
    return 1 - wape(b.boardings.values, pred * kr)

def run(name, folds=ORDER, **kw):
    r = {f: predict(f, **kw) for f in folds}
    m4 = np.mean([r[f] for f in folds]); m3 = np.mean([r[f] for f in ['F4','F2','F1']])
    print(f"{name:<52} " + "  ".join(f"{f}:{r[f]:.4f}" for f in folds) + f" | ср.4 {m4:.4f} | ср.3 {m3:.4f}", flush=True)
    return r, m4, m3
