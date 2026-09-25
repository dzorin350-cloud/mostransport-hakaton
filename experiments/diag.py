import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
out_all=[]
for fold in ['F1','F4','F2']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)].copy()
    fac=seas(o,sorted(te.date.dt.month.unique()))
    p,cb,pf=forecast(tr,te[['route','date','hour']],best,seeds=3,fac=fac); te['p']=p; te['e']=te.p-te.boardings; te['fold']=fold
    out_all.append(te)
    y=te.boardings.sum(); print(f"\n===== {fold} ({s}..{e}) score={1-te.e.abs().sum()/y:.4f}")
    r=te.groupby('route').apply(lambda g:pd.Series({'вклад в ошибку %':g.e.abs().sum()/te.e.abs().sum()*100,'WAPE маршрута':g.e.abs().sum()/g.boardings.sum(),'смещение %':(g.p.sum()/g.boardings.sum()-1)*100}))
    print(r.round(3).to_string())
    # разложение: масштаб на маршрут за период / на маршрут-день
    a=te.copy(); a['p1']=a.p*a.route.map(a.groupby('route').boardings.sum()/a.groupby('route').p.sum())
    d=a.groupby(['route','date'])[['boardings','p']].transform('sum'); a['p2']=a.p*(d.boardings/d.p.replace(0,np.nan)).fillna(1)
    sc=lambda c:1-(a[c]-a.boardings).abs().sum()/y
    print(f"score: как есть {sc('p'):.4f} | если уровень маршрута за период идеален {sc('p1'):.4f} | если идеален итог по каждому маршруту и дню {sc('p2'):.4f}")
    print("  → ошибка уровня маршрутов:",round(sc('p1')-sc('p'),4),"| ошибка суточных итогов:",round(sc('p2')-sc('p1'),4),"| остаток (доли по часам + шум):",round(1-sc('p2'),4))
al=pd.concat(out_all)
al['dt']=np.where(al.date.dt.dayofweek<5,'будни',np.where(al.date.dt.dayofweek==5,'суббота','воскресенье'))
h=al.groupby('hour').apply(lambda g:pd.Series({'вклад в ошибку %':g.e.abs().sum()/al.e.abs().sum()*100,'WAPE часа':g.e.abs().sum()/max(g.boardings.sum(),1),'смещение %':(g.p.sum()/max(g.boardings.sum(),1)-1)*100}))
print("\n===== по часам (3 периода вместе)"); print(h.round(1).T.to_string())
print("\n===== по типу дня"); print(al.groupby('dt').apply(lambda g:pd.Series({'вклад в ошибку %':g.e.abs().sum()/al.e.abs().sum()*100,'WAPE':g.e.abs().sum()/g.boardings.sum(),'смещение %':(g.p.sum()/g.boardings.sum()-1)*100})).round(3).to_string())
