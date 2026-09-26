"""Коридор прогноза (80 %): квантили отношения факт/прогноз по горизонту и детализации из честных бэктестов.
Калибровка: периоды май–июнь, июль–август, март–апрель + длинные бэктесты (старты фев/мар/апр → до октября).
Проверка покрытия: отложенный сен–окт (обучение до 31.08)."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
from clean import *
rows = []
for fold in ['F1', 'F2', 'F3', 'F4']:
    o, s, e = FOLDS[fold]; o = pd.Timestamp(o); tr = G[G.date <= o].reset_index(drop=True); te = G[(G.date >= s) & (G.date <= e)].copy()
    fr = te[['route', 'date', 'hour']]; fac = seas(o, sorted(te.date.dt.month.unique())); b = build(fr); w = np.where(b.dow.values >= 5, 0.8, 0.6); hol = b.hol_wd.values == 1
    c = clean_grid(tr, 1.5, protect_weeks=0)[0]; _, cb, pf = forecast(c, fr, best, seeds=2, fac=fac)
    te['pred'] = np.where(hol, cb, w * cb + (1 - w) * pf); te['origin'] = o; te['src'] = fold; rows.append(te[['route', 'date', 'hour', 'boardings', 'pred', 'origin', 'src']]); print(fold, flush=True)
L = pd.read_parquet('/Users/denis/Documents/Данные хакатон Мос Транспорт/year_model/ym_route_backtest.parquet').reset_index(drop=True)
L = L.rename(columns={'текущий': 'pred'}); L['origin'] = pd.to_datetime(L['origin'] + '-01') + pd.offsets.MonthEnd(0); L['src'] = 'long'
A = pd.concat(rows + [L[['route', 'date', 'hour', 'boardings', 'pred', 'origin', 'src']]], ignore_index=True)
A['ahead'] = (A.date - A.origin).dt.days
BUCKETS = [(1, 7, '1–7 дней'), (8, 30, '8–30 дней'), (31, 61, '31–61 день'), (62, 120, '2–4 месяца'), (121, 400, '4–12 месяцев')]
def bucket(d):
    for a, b_, lab in BUCKETS:
        if a <= d <= b_: return lab
A['bucket'] = A.ahead.map(bucket); A = A[A.bucket.notna()]
A['week'] = A.date - pd.to_timedelta(A.date.dt.dayofweek, 'D'); A['month'] = A.date.dt.to_period('M')
def agg(df, level):
    keys = {'hour': ['route', 'date', 'hour'], 'day': ['route', 'date'], 'week': ['route', 'week'], 'month': ['route', 'month']}[level]
    g = df.groupby(keys + ['bucket', 'src'], observed=True)[['boardings', 'pred']].sum().reset_index()
    g = g[g.pred >= (20 if level == 'hour' else 100)]
    g['r'] = g.boardings / g.pred; return g
out, cov = [], []
for level in ['hour', 'day', 'week', 'month']:
    g = agg(A, level); cal, test = g[g.src != 'F1'], g[g.src == 'F1']
    for _, _, lab in BUCKETS:
        c = cal[cal.bucket == lab]
        if len(c) < 30: continue
        lo, hi = c.r.quantile(0.10), c.r.quantile(0.90); out.append((level, lab, round(lo, 3), round(hi, 3), len(c)))
        t = test[test.bucket == lab]
        if len(t): cov.append((level, lab, f"{((t.r >= lo) & (t.r <= hi)).mean():.0%}", len(t)))
F = pd.DataFrame(out, columns=['level', 'bucket', 'lo', 'hi', 'n'])
F.to_csv('interval_factors.csv', index=False)
print("\nКоридор 80 %: прогноз × [lo; hi]"); print(F.to_string(index=False))
print("\nПокрытие на отложенном сен–окт (цель ≈ 80 %):"); print(pd.DataFrame(cov, columns=['level', 'bucket', 'покрытие', 'n']).to_string(index=False))
