"""Загрузка вагонов и рекомендация выпуска: честная проверка. Нормы — только по данным до 31.08.2025, прогноз v7 на сен–окт,
сравнение с фактом (посадки и число вагонов с валидациями в этот час)."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
from clean import *
S = pd.read_parquet('/private/tmp/claude-501/-Users-denis-Documents-----------------------------/a80979ab-a6d9-4bf4-a59c-2fd0a2eacbbd/scratchpad/supply_hourly.parquet')
S = S[S.route.isin(ROUTES)][['route', 'date', 'hour', 'veh', 'ok']]
def norms(until, weeks=8):
    x = S[(S.date <= until) & (S.date > until - pd.Timedelta(weeks=weeks))].copy(); x['dt'] = dtype(x.date)
    x['bpv'] = x.ok / x.veh.replace(0, np.nan)
    n = x.groupby(['route', 'dt', 'hour']).agg(veh_typ=('veh', 'median')).reset_index()
    pk = x[(x.dt == 'wd') & x.hour.between(7, 20)].groupby('route').bpv
    th = pd.DataFrame({'bpv_med': pk.median(), 'bpv_high': pk.quantile(0.9)}).reset_index()
    return n.merge(th, on='route')
o = pd.Timestamp('2025-08-31'); tr = G[G.date <= o].reset_index(drop=True); te = G[(G.date >= '2025-09-01') & (G.date <= '2025-10-31')].copy()
fr = te[['route', 'date', 'hour']]; fac = seas(o, [9, 10]); b = build(fr); w = np.where(b.dow.values >= 5, 0.8, 0.6); hol = b.hol_wd.values == 1
c = clean_grid(tr, 1.5, protect_weeks=0)[0]; _, cb, pf = forecast(c, fr, best, seeds=2, fac=fac); te['pred'] = np.where(hol, cb, w * cb + (1 - w) * pf)
te['dt'] = dtype(te.date); N = norms(o)
d = te.merge(N, on=['route', 'dt', 'hour'], how='left').merge(S, on=['route', 'date', 'hour'], how='left')
d = d[(d.hour.between(6, 21)) & (d.veh > 0)]
d['bpv_fact'] = d.ok / d.veh; d['bpv_pred'] = d.pred / d.veh_typ
d['load_pred'] = d.bpv_pred / d.bpv_high; d['load_fact'] = d.bpv_fact / d.bpv_high
def cls(x): return np.where(x > 1.0, 'риск', np.where(x > 0.85, 'повышенная', 'норма'))
d['c_pred'] = cls(d.load_pred); d['c_fact'] = cls(d.load_fact)
print("часов (маршрут × час, 6–21 ч):", len(d))
print("\nФакт ↓ / прогноз →"); print(pd.crosstab(d.c_fact, d.c_pred).reindex(index=['норма', 'повышенная', 'риск'], columns=['норма', 'повышенная', 'риск']).to_string())
tp = ((d.c_pred == 'риск') & (d.c_fact == 'риск')).sum(); pp = (d.c_pred == 'риск').sum(); ap = (d.c_fact == 'риск').sum()
print(f"\n«риск переполнения»: предсказано {pp}, было на самом деле {ap}, совпало {tp} → точность {tp/max(pp,1):.2f}, полнота {tp/max(ap,1):.2f}")
tp2 = ((d.c_pred != 'норма') & (d.c_fact != 'норма')).sum(); print(f"«повышенная или риск»: точность {tp2/max((d.c_pred!='норма').sum(),1):.2f}, полнота {tp2/max((d.c_fact!='норма').sum(),1):.2f}")
print("корреляция прогнозной и фактической загрузки вагона:", round(d.load_pred.corr(d.load_fact), 3))
# рекомендация: вагонов = ceil(прогноз / медианные посадки на вагон)
d['veh_rec'] = np.ceil(d.pred / d.bpv_med).clip(lower=1); d['veh_need_fact'] = np.ceil(d.ok / d.bpv_med).clip(lower=1)
print("\nРекомендация вагонов против «нужно по факту» (при той же норме загрузки): средняя |ошибка|", round((d.veh_rec - d.veh_need_fact).abs().mean(), 2),
      "вагона; совпадает ±1 вагон в", f"{((d.veh_rec - d.veh_need_fact).abs() <= 1).mean():.0%}", "часов")
wd = d[d.dt == 'wd']
print("будни: фактический выпуск (вагоно-часов в день, 6–21 ч)", round(wd.groupby('date').veh.sum().mean()), "| рекомендованный", round(wd.groupby('date').veh_rec.sum().mean()))
pk = wd[wd.hour.isin([7, 8, 17, 18])]; op = wd[wd.hour.isin([10, 11, 12, 13, 14, 20, 21])]
print("  пик (7–8, 17–18): факт", round(pk.groupby('date').veh.sum().mean()), "рекоменд.", round(pk.groupby('date').veh_rec.sum().mean()),
      "| межпик (10–14, 20–21): факт", round(op.groupby('date').veh.sum().mean()), "рекоменд.", round(op.groupby('date').veh_rec.sum().mean()))
d.to_parquet('fleet_backtest_sep_oct.parquet')
