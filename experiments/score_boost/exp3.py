from harness import *
import harness
print('--- смещение прогноза (Σпрогноз/Σфакт − 1) по фолдам и маршрутам')
def post_bias(pred,b,tr):
    s=pred.sum()/b.boardings.sum()-1; r=b.assign(p=pred).groupby('route').apply(lambda g:g.p.sum()/g.boardings.sum()-1)
    print(f"   {b.date.min().date()}: сеть {s:+.1%} | "+" ".join(f"{k}:{v:+.0%}" for k,v in r.items())); return pred
evaluate('смещение',post_fn=post_bias)
print('--- очистка обучения')
evaluate('без очистки',clean_cfg=None)
for thr in [1.3,1.4,1.7,2.0]: evaluate(f'очистка thr={thr}',clean_cfg=dict(thr=thr,protect_weeks=0))
for wk in [0.10,0.20,0.25]: evaluate(f'очистка thr=1.5 wk_thr={wk}',clean_cfg=dict(thr=1.5,wk_thr=wk,protect_weeks=0))
print('--- уровень с трендом маршрута (последние 4 нед. к предыдущим 4, будни), с затуханием')
def lvl_trend(alpha):
    def fn(tr,b):
        o=tr.date.max(); c=tr.merge(cal(tr.date.unique()),on='date'); c=c[c.off==0]
        d=c.groupby(['route','date']).boardings.sum().reset_index()
        a=d[d.date>o-pd.Timedelta(weeks=4)].groupby('route').boardings.mean(); p=d[(d.date<=o-pd.Timedelta(weeks=4))&(d.date>o-pd.Timedelta(weeks=8))].groupby('route').boardings.mean()
        g=(a/p).clip(0.9,1.1)
        L=tr[tr.date>o-pd.Timedelta(days=56)].groupby('route').boardings.sum()/56
        return (b.route.map(L)*(1+alpha*(b.route.map(g)-1))).values
    return fn
for al in [0.5,1.0]: evaluate(f'уровень × тренд^{al}',level_fn=lvl_trend(al))
def lvl_recent(days):
    def fn(tr,b):
        o=tr.date.max(); L56=tr[tr.date>o-pd.Timedelta(days=56)].groupby('route').boardings.sum()/56
        Lr=tr[tr.date>o-pd.Timedelta(days=days)].groupby('route').boardings.sum()/days
        return b.route.map(0.5*L56+0.5*Lr).values
    return fn
evaluate('уровень = ½·56 дн. + ½·28 дн.',level_fn=lvl_recent(28))
print('--- сезонность: базовый месяц — среднее двух последних месяцев')
import clean
def seas2(o,months):
    P=clean.P; yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month,o.month-1]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/(0.5*P.loc[y,o.month]+0.5*P.loc[y,o.month-1]) for y in yrs])) for m in months}
