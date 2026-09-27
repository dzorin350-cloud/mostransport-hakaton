"""Стенд экспериментов поверх кода итоговой модели: те же фолды, очистка, уровень, сезонность, смесь.
Меняется: набор признаков, очистка, параметры смеси/уровня/профиля. CatBoost-прогнозы кэшируются."""
import hashlib, json, os, sys, time
import numpy as np, pandas as pd
from catboost import CatBoostRegressor
from clean import G, cal, wape, best, seas, clean_grid, DAYOFF, FOLDS

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache"); os.makedirs(CACHE, exist_ok=True)
BASE_FEATS = ['route', 'hour', 'dow', 'off', 'hol_wd', 'pre', 'post']
ORDER = ['F3', 'F4', 'F2', 'F1']          # мар–апр, май–июн, июл–авг, сен–окт

def is_off(d): return (d in DAYOFF) or d.dayofweek >= 5

def build_x(dates):
    """все кандидаты в признаки на дату (только календарь/астрономия — известно заранее)"""
    c = cal(dates)
    d = c.date
    c['month'] = d.dt.month; c['woy'] = d.dt.isocalendar().week.astype(int); c['doy'] = d.dt.dayofyear
    # дней до / после ближайшего нерабочего блока
    def dist(dd, step):
        k = 0
        x = dd
        while k < 10:
            x = x + pd.Timedelta(days=step); k += 1
            if is_off(x): return k
        return 10
    c['to_off'] = [dist(x, 1) for x in d]; c['from_off'] = [dist(x, -1) for x in d]
    c['pre2'] = ((c.to_off == 2) & (c.off == 0)).astype(int)
    # длинные праздничные блоки (≥3 нерабочих подряд)
    def block_len(dd):
        if not is_off(dd): return 0
        a = dd; n = 1
        while is_off(a - pd.Timedelta(days=1)): a -= pd.Timedelta(days=1); n += 1
        b = dd
        while is_off(b + pd.Timedelta(days=1)): b += pd.Timedelta(days=1); n += 1
        return n
    c['block'] = [block_len(x) for x in d]
    # световой день Москвы (55.75N): длина дня и час заката (UTC+3), грубая астрономическая формула
    doy = c.doy.values; lat = np.radians(55.75)
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    ha = np.degrees(np.arccos(np.clip(-np.tan(lat) * np.tan(decl), -1, 1)))
    c['daylen'] = 2 * ha / 15
    c['sunset'] = 12 + ha / 15 + (3 - 37.62 / 15)        # солнечный полдень ≈ 12:30 МСК
    c['dow_off'] = c.dow * 2 + c.off
    return c

def fold_data(fold, clean_cfg):
    o, s, e = FOLDS[fold]; o = pd.Timestamp(o)
    tr = G[G.date <= o].copy(); te = G[(G.date >= s) & (G.date <= e)].copy()
    if clean_cfg is not None:
        cfg = dict(clean_cfg); hk = cfg.pop('hour_k', None)
        tr, _ = clean_grid(tr, **cfg)
        if hk: tr = clean_hours(tr, hk)
    return tr, te

def clean_hours(tr, k):
    """выбросы отдельных часов: доля часа в сутках против типичной доли (маршрут, тип дня, час) вне [1/k, k] → типичная доля"""
    from clean import dtype
    t = tr.copy(); t['dt'] = dtype(t.date)
    tot = t.groupby(['route','date']).boardings.transform('sum'); t['sh'] = t.boardings / tot.replace(0, np.nan)
    typ = t.groupby(['route','dt','hour']).sh.transform('median')
    r = t.sh / typ
    bad = (typ > 0.01) & ((r > k) | (r < 1 / k)) & (tot > 0)
    t.loc[bad, 'boardings'] = (tot * typ)[bad]
    t = t[['route','date','hour','boardings']]
    t.attrs['n_bad'] = int(bad.sum()); return t

def _key(*a): return hashlib.md5(json.dumps(a, sort_keys=True, default=str).encode()).hexdigest()[:16]

def cb_share(fold, clean_cfg, feats, cats, p, seed, extra_fn=None, extra_name=None):
    """прогноз доли часа от уровня (сырое предсказание CatBoost) на тестовые строки фолда"""
    k = _key(fold, clean_cfg, feats, cats, {x: p[x] for x in ('loss','iters','depth','lr','l2','rs','boot','bt','ss','vp','norm_win')}, seed, extra_name)
    f = os.path.join(CACHE, k + ".npy")
    if os.path.exists(f): return np.load(f)
    tr, te = fold_data(fold, clean_cfg)
    ctr = build_x(tr.date.unique()); cte = build_x(te.date.unique())
    a = tr.merge(ctr, on='date'); b = te.merge(cte, on='date')
    if extra_fn is not None: a, b = extra_fn(a, tr), extra_fn(b, tr)
    dd = tr.groupby(['route','date']).boardings.sum().unstack(0)
    L = dd.rolling(p['norm_win'], center=True, min_periods=10).mean().stack().rename('L').reset_index()
    a = a.merge(L, on=['route','date']); a = a[a.L > 0]
    def X(df):
        x = df[feats].copy()
        for c in cats: x[c] = x[c].astype(int) if c != 'dow_hour' else x[c].astype(str)
        return x
    kw = dict(loss_function=p['loss'], iterations=p['iters'], depth=p['depth'], learning_rate=p['lr'], l2_leaf_reg=p['l2'],
              random_strength=p['rs'], cat_features=cats, random_seed=seed, verbose=0, thread_count=10,
              bootstrap_type='Bernoulli', subsample=p['ss'])
    m = CatBoostRegressor(**kw); m.fit(X(a), a.boardings / a.L, sample_weight=a.L)
    out = np.clip(m.predict(X(b)), 0, None); np.save(f, out); return out

def evaluate(name, feats=BASE_FEATS, cats=('route',), clean_cfg=dict(thr=1.5, protect_weeks=0), p=None, seeds=2,
             w_wd=0.6, w_we=0.8, lvl=None, weeks=None, prof_agg='mean', extra_fn=None, extra_name=None, level_fn=None,
             post_fn=None, folds=ORDER, verbose=True):
    p = dict(best, **(p or {})); lvl = lvl or p['lvl']; weeks = weeks or p['weeks']; cats = list(cats)
    res = {}
    for fold in folds:
        tr, te = fold_data(fold, clean_cfg); o = tr.date.max()
        cte = build_x(te.date.unique()); b = te.merge(cte, on='date')
        months = sorted(te.date.dt.month.unique()); fac = seas(o, months); f = b.date.dt.month.map(fac).values
        sh = np.mean([cb_share(fold, clean_cfg, list(feats), cats, p, s, extra_fn, extra_name) for s in range(seeds)], axis=0)
        if level_fn is None:
            L = tr[tr.date > o - pd.Timedelta(days=lvl)].groupby('route').boardings.sum() / lvl
            Lv = b.route.map(L).values
        else:
            Lv = level_fn(tr, b)
        cb = sh * Lv * f
        t = tr[tr.date > o - pd.Timedelta(weeks=weeks)].merge(cal(tr.date.unique()), on='date'); t = t[t.hol_wd == 0]
        PR = t.groupby(['route','dow','hour']).boardings.agg(prof_agg).rename('pp').reset_index()
        pf = b.merge(PR, on=['route','dow','hour'], how='left').pp.fillna(0).values * f
        w = np.where(b.dow.values >= 5, w_we, w_wd)
        pred = np.where(b.hol_wd.values == 1, cb, w * cb + (1 - w) * pf)
        if post_fn is not None: pred = post_fn(pred, b, tr)
        res[fold] = 1 - wape(b.boardings.values, pred)
    res['mean'] = float(np.mean([res[x] for x in folds]))
    if verbose:
        print(f"{name:<55} " + "  ".join(f"{x}:{res[x]:.4f}" for x in folds) + f"  | mean {res['mean']:.4f}", flush=True)
    return res
