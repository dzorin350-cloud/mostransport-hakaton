"""Вариант 2: порог загрузки по всей истории до даты (устойчив к сезону), рекомендация — минимум вагонов без превышения порога."""
import sys; sys.path.insert(0, '/Users/denis/Documents/Данные хакатон Мос Транспорт/FROZEN_v7_score_0.88399/code')
from clean import dtype
import pandas as pd, numpy as np
d = pd.read_parquet('fleet_backtest_sep_oct.parquet')
S = pd.read_parquet('/private/tmp/claude-501/-Users-denis-Documents-----------------------------/a80979ab-a6d9-4bf4-a59c-2fd0a2eacbbd/scratchpad/supply_hourly.parquet')
x = S[(S.date <= '2025-08-31') & (S.date >= '2025-01-09')].copy(); x['dt'] = dtype(x.date); x['bpv'] = x.ok / x.veh.replace(0, np.nan)
pk = x[(x.dt == 'wd') & x.hour.between(7, 20)].groupby('route').bpv
TH = pd.DataFrame({'p75': pk.quantile(.75), 'p90': pk.quantile(.9), 'p95': pk.quantile(.95)})
d = d.drop(columns=['bpv_med', 'bpv_high']).join(TH, on='route')
def cls(v): return np.where(v > 1.0, 'риск', np.where(v > 0.85, 'повышенная', 'норма'))
for th in ['p90', 'p95']:
    lp, lf = d.bpv_pred / d[th], d.bpv_fact / d[th]; cp, cf = cls(lp), cls(lf)
    tp = ((cp == 'риск') & (cf == 'риск')).sum()
    print(f"\nпорог {th}: доля часов «риск» по факту {np.mean(cf=='риск'):.1%}, по прогнозу {np.mean(cp=='риск'):.1%} | точность {tp/max((cp=='риск').sum(),1):.2f}, полнота {tp/max((cf=='риск').sum(),1):.2f}")
    print(pd.crosstab(pd.Series(cf, name='факт'), pd.Series(cp, name='прогноз')).reindex(index=['норма','повышенная','риск'], columns=['норма','повышенная','риск']).to_string())
wd = d[d.dt == 'wd']
for tgt in ['p75', 'p90']:
    rec = np.ceil(wd.pred / wd[tgt]).clip(lower=1); need = np.ceil(wd.ok / wd[tgt]).clip(lower=1)
    print(f"\nрекомендация «не выше {tgt}»: будни, вагоно-часов в день 6–21 ч — факт выпуска {wd.groupby('date').veh.sum().mean():.0f}, рекомендовано {rec.groupby(wd.date).sum().mean():.0f}, "
          f"нужно по факту спроса {need.groupby(wd.date).sum().mean():.0f} | |рекоменд. − нужно по факту| = {np.abs(rec-need).mean():.2f} ваг., ±1 ваг. в {(np.abs(rec-need)<=1).mean():.0%} часов")
    for lab, hh in [('пик 7–8, 17–18', [7, 8, 17, 18]), ('межпик 10–14, 20–21', [10, 11, 12, 13, 14, 20, 21])]:
        m = wd.hour.isin(hh); print(f"   {lab}: факт {wd[m].groupby('date').veh.sum().mean():.0f}, рекоменд. {rec[m].groupby(wd.date[m]).sum().mean():.0f}, нужно по факту {need[m].groupby(wd.date[m]).sum().mean():.0f}")
