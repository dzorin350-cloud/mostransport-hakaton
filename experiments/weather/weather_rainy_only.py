"""v7 + погода только в сильно дождливые дни (3+ дневных срока с дождём).
A: прогноз v7 × (1 + b·дождь) только в сильно дождливые дни; сухие и слабо дождливые не трогаются.
B: то же + в обучении сильно дождливые дни приводятся к «сухому» уровню (чтобы дождь не занижал уровень и профиль).
Погода прогнозного дня — фактическая (имитация точного прогноза погоды на завтра); для ноября–декабря 2025 такого прогноза нет."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code'); sys.path.insert(0, 'experiments/weather')
from weather_eval import *
THR = 3
def fit_rain(tr):
    d = tr.groupby(['route', 'date']).boardings.sum().reset_index(); d['dt'] = dtype(d.date); d = d[d.dt != 'hol']
    d['exp'] = d.groupby(['route', 'dt']).boardings.transform(lambda s: s.rolling(11, center=True, min_periods=3).median())
    n = d.groupby('date').apply(lambda g: g.boardings.sum() / g.exp.sum()).rename('r').to_frame().join(W[['rain']]).dropna()
    n = n[(n.r > 0.75) & (n.r < 1.33)]
    heavy = n[n.rain >= THR]; return float((heavy.r / 1.0).mean() - n[n.rain == 0].r.mean())   # эффект сильно дождливого дня против сухого
rows = []; eff = {}
for fold in ['F1', 'F4', 'F2', 'F3']:
    o, s, e = FOLDS[fold]; o = pd.Timestamp(o); tr = G[G.date <= o].reset_index(drop=True); te = G[(G.date >= s) & (G.date <= e)].copy()
    fr = te[['route', 'date', 'hour']]; fac = seas(o, sorted(te.date.dt.month.unique())); b = build(fr); w = np.where(b.dow.values >= 5, 0.8, 0.6); hol = b.hol_wd.values == 1
    c = clean_grid(tr, 1.5, protect_weeks=0)[0]; k = fit_rain(c); eff[fold] = k
    heavy_te = te.date.map(W.rain).fillna(0).values >= THR
    _, cb, pf = forecast(c, fr, best, seeds=2, fac=fac); te['p0'] = np.where(hol, cb, w * cb + (1 - w) * pf)
    te['pA'] = te.p0 * np.where(heavy_te, 1 + k, 1.0)
    heavy_tr = c.date.map(W.rain).fillna(0).values >= THR; cB = c.copy(); cB['boardings'] = c.boardings.values / np.where(heavy_tr, 1 + k, 1.0)
    _, cb2, pf2 = forecast(cB, fr, best, seeds=2, fac=fac); pB0 = np.where(hol, cb2, w * cb2 + (1 - w) * pf2)
    te['pB'] = pB0 * np.where(heavy_te, 1 + k, 1.0); te['pB_clim'] = pB0          # B без прогноза погоды (как было бы в сабмите)
    te['heavy'] = heavy_te; te['fold'] = fold; rows.append(te); print(fold, f"эффект сильно дождливого дня {k:+.3f}", flush=True)
A = pd.concat(rows)
def sc(d, c): return 1 - (d.boardings - d[c]).abs().sum() / d.boardings.sum()
print("\n(1 − WAPE), 4 периода вместе; погода дня — фактическая (идеальный прогноз на завтра)")
print(f"{'':34s} {'v7':>7s} {'A: только поправка':>19s} {'B: + очистка обучения':>22s} {'B без прогноза погоды':>22s}")
for lab, d in [('все дни', A), ('сильно дождливые дни', A[A.heavy]), ('остальные дни', A[~A.heavy])]:
    print(f"{lab:34s} {sc(d,'p0'):7.4f} {sc(d,'pA'):19.4f} {sc(d,'pB'):22.4f} {sc(d,'pB_clim'):22.4f}")
print("\nпо периодам (все дни):"); print(A.groupby('fold').apply(lambda d: pd.Series({c: round(sc(d, c), 4) for c in ['p0', 'pA', 'pB', 'pB_clim']})).to_string())
print("сильно дождливых дней:", A[A.heavy].groupby('fold').date.nunique().to_dict())
