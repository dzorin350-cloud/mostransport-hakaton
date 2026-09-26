"""Погода на уровне дня: улучшает ли поправка по фактической погоде (≈ идеальный прогноз на завтра) ошибку конкретных дней."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
sys.path.insert(0, 'experiments/weather')
from weather_eval import *
rows = []
for fold in ['F1', 'F4', 'F2', 'F3']:
    o, s, e = FOLDS[fold]; o = pd.Timestamp(o); tr = G[G.date <= o].reset_index(drop=True); te = G[(G.date >= s) & (G.date <= e)].copy()
    fr = te[['route', 'date', 'hour']]; fac = seas(o, sorted(te.date.dt.month.unique())); b = build(fr); w = np.where(b.dow.values >= 5, 0.8, 0.6); hol = b.hol_wd.values == 1
    c = clean_grid(tr, 1.5, protect_weeks=0)[0]; bb = residual_fit(c)
    tw = c.merge(W[WF].reset_index(), on='date', how='left').fillna(0); dry = c.copy(); dry['boardings'] = c.boardings.values / fac_w(bb, tw)
    _, cb0, pf0 = forecast(c, fr, best, seeds=2, fac=fac); te['p0'] = np.where(hol, cb0, w * cb0 + (1 - w) * pf0)
    _, cb2, pf2 = forecast(dry, fr, best, seeds=2, fac=fac); base2 = np.where(hol, cb2, w * cb2 + (1 - w) * pf2)
    dts = pd.DatetimeIndex(sorted(te.date.unique()), name='date'); fa = pd.Series(fac_w(bb, W.reindex(dts)[WF].fillna(0)), index=dts)
    te['p1'] = base2 * te.date.map(fa).values
    te = te.join(W[['rain']], on='date'); te['fold'] = fold; rows.append(te); print(fold, 'готово', flush=True)
A = pd.concat(rows)
D = A.groupby(['fold', 'date']).apply(lambda g: pd.Series({'y': g.boardings.sum(), 'e0': (g.boardings - g.p0).abs().sum(), 'e1': (g.boardings - g.p1).abs().sum(),
                                                            'b0': g.p0.sum() / g.boardings.sum() - 1, 'b1': g.p1.sum() / g.boardings.sum() - 1, 'rain': g.rain.iloc[0]})).reset_index()
def sc(d, c): return 1 - d[c].sum() / d.y.sum()
print("\nСкор по часам внутри дня (1 − WAPE), 4 периода вместе:")
for lab, d in [('все дни', D), ('сухие дни (0 сроков с дождём)', D[D.rain == 0]), ('дождь 1–2 срока', D[D.rain.between(1, 2)]), ('дождь 3+ срока (сильно дождливые)', D[D.rain >= 3])]:
    print(f"  {lab:36s} дней {len(d):3d} | без погоды {sc(d,'e0'):.4f} | с погодой {sc(d,'e1'):.4f} | разница {sc(d,'e1')-sc(d,'e0'):+.4f} | смещение {d.b0.mean():+.3f} → {d.b1.mean():+.3f}")
print("  доля дней, где с погодой лучше:", round((D.e1 < D.e0).mean(), 3))
