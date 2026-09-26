"""Погода (pogodaiklimat.ru, Москва-ВДНХ) в модели v7: признак CatBoost и поправка поверх модели. Валидация на 4 периодах."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
from clean import *
W = pd.read_csv('/Users/denis/Documents/Данные хакатон Мос Транспорт/external/weather_ru/pogodaiklimat_27612_daily_2022-01_2025-10.csv', parse_dates=['date']).set_index('date')
W = W[W.index <= '2025-10-31']
W['rain'] = W.rain_obs_day.clip(0, 6); W['snow'] = W.snow_obs_day.clip(0, 6); W['t'] = W.t_mean.interpolate()
WF = ['rain', 'snow', 't']
def clim(dates, upto):
    """норма: среднее по тем же ±7 дням года за годы строго до года прогноза и только по данным <= upto"""
    h = W[W.index <= upto]; out = []
    for d in dates:
        v = [h.loc[pd.Timestamp(year=y, month=d.month, day=min(d.day, 28)) - pd.Timedelta(days=7):pd.Timestamp(year=y, month=d.month, day=min(d.day, 28)) + pd.Timedelta(days=7), WF].mean()
             for y in range(2022, d.year) if pd.Timestamp(year=y, month=d.month, day=1) <= upto]
        out.append(pd.concat(v, axis=1).mean(axis=1) if v else h[WF].mean())
    return pd.DataFrame(out, index=pd.DatetimeIndex(dates, name='date'))
def residual_fit(tr):
    """эластичность: отношение факта к ожидаемому (медиана того же типа дня ±5 нед.) ~ дождь + снег, по сети"""
    d = tr.groupby(['route', 'date']).boardings.sum().reset_index(); d['dt'] = dtype(d.date); d = d[d.dt != 'hol']
    d['exp'] = d.groupby(['route', 'dt']).boardings.transform(lambda s: s.rolling(11, center=True, min_periods=3).median())
    n = d.groupby('date').apply(lambda g: g.boardings.sum() / g.exp.sum()).rename('r').to_frame().join(W[WF]).dropna()
    n = n[(n.r > 0.75) & (n.r < 1.33)]
    X = np.c_[n.rain, n.snow]; b = np.linalg.lstsq(np.c_[np.ones(len(n)), X], n.r.values, rcond=None)[0]
    return b                                              # r = b0 + b_rain*rain + b_snow*snow
def fac_w(b, wdf): return (1 + b[1] * wdf.rain.values + b[2] * wdf.snow.values).clip(0.8, 1.1)
def run(fold):
    o, s, e = FOLDS[fold]; o = pd.Timestamp(o); tr = G[G.date <= o].reset_index(drop=True); te = G[(G.date >= s) & (G.date <= e)]
    y = te.boardings.values; fr = te[['route', 'date', 'hour']]; fac = seas(o, sorted(te.date.dt.month.unique()))
    b = build(fr); w = np.where(b.dow.values >= 5, 0.8, 0.6); hol = b.hol_wd.values == 1
    c = clean_grid(tr, 1.5, protect_weeks=0)[0]
    _, cb, pf = forecast(c, fr, best, seeds=2, fac=fac); base = np.where(hol, cb, w * cb + (1 - w) * pf)
    res = {'v7': 1 - wape(y, base)}
    # (2) поправка поверх модели
    bb = residual_fit(c); dts = pd.DatetimeIndex(sorted(te.date.unique()), name='date')
    tw = c.merge(W[WF].reset_index(), on='date', how='left').fillna(0); dry = c.copy(); dry['boardings'] = c.boardings.values / fac_w(bb, tw)
    _, cb2, pf2 = forecast(dry, fr, best, seeds=2, fac=fac); base2 = np.where(hol, cb2, w * cb2 + (1 - w) * pf2)
    cl = clim(dts, o); fc_cl = pd.Series(fac_w(bb, cl), index=dts); fc_act = pd.Series(fac_w(bb, W.reindex(dts)[WF].fillna(0)), index=dts)
    res['поправка, норма'] = 1 - wape(y, base2 * te.date.map(fc_cl).values)
    res['поправка, факт (потолок)'] = 1 - wape(y, base2 * te.date.map(fc_act).values)
    # (1) признак CatBoost
    trb = build(c).merge(W[WF].reset_index(), on='date', how='left'); trb[WF] = trb[WF].fillna(trb[WF].mean())
    dd = c.groupby(['route', 'date']).boardings.sum().unstack(0); L = dd.rolling(best['norm_win'], center=True, min_periods=10).mean().stack().rename('L').reset_index()
    cc = trb.merge(L, on=['route', 'date']); cc = cc[cc.L > 0]; F2 = FEATS + WF
    X = cc[F2].copy(); X['route'] = X.route.astype(int)
    Lf = c[c.date > o - pd.Timedelta(days=best['lvl'])].groupby('route').boardings.sum() / best['lvl']; f = te.date.dt.month.map(fac).values
    for lab, wx in [('признак, норма', cl), ('признак, факт (потолок)', W.reindex(dts)[WF].fillna(0))]:
        fb = b.merge(wx.reset_index(), on='date', how='left'); Xt = fb[F2].copy(); Xt['route'] = Xt.route.astype(int)
        ps = []
        for sd in range(2):
            m = CatBoostRegressor(loss_function='RMSE', iterations=best['iters'], depth=best['depth'], learning_rate=best['lr'], l2_leaf_reg=best['l2'], random_strength=best['rs'], bootstrap_type='Bernoulli', subsample=best['ss'], cat_features=['route'], random_seed=sd, verbose=0, thread_count=10)
            m.fit(X, cc.boardings / cc.L, sample_weight=cc.L); ps.append(np.clip(m.predict(Xt), 0, None))
        cbw = np.mean(ps, axis=0) * fb.route.map(Lf).values * f
        res[lab] = 1 - wape(y, np.where(hol, cbw, w * cbw + (1 - w) * pf))
    res['эластичность: дождь, снег (на 1 срок)'] = f"{bb[1]:+.4f}, {bb[2]:+.4f}"
    return res
rows = {}
for fold, lab in [('F1', 'сен–окт (test)'), ('F4', 'май–июнь'), ('F2', 'июль–август'), ('F3', 'март–апрель')]:
    rows[lab] = run(fold); print(lab, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[lab].items()}, flush=True)
T = pd.DataFrame(rows).T; num = [c for c in T if not c.startswith('эласт')]
T.loc['среднее', num] = T[num].astype(float).mean()
print(T.to_string())
