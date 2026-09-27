from boost2 import *
B={f:fold_pred(f) for f in ORDER}
base={f:score(B[f][0]) for f in ORDER}
show('итоговая модель',base)
show('итоговая модель (без мар–апр)',base,['F4','F2','F1'])
print('=== 1. Коррекция остатков формы дня: учим на предыдущем фолде (его факт известен к старту), применяем к следующему')
PREV={'F4':'F3','F2':'F4','F1':'F2'}
def corr(keys, alpha, clip=(0.8,1.25), shape_only=True, min_share=0.0):
    res={}
    for f,pf in PREV.items():
        bp,_=B[pf]; b=B[f][0].copy()
        g=bp.groupby(keys).agg(y=('boardings','sum'),p=('pred','sum')).reset_index(); g['k']=(g.y/g.p.replace(0,np.nan)).clip(*clip).fillna(1)
        g['k']=1+alpha*(g.k-1)
        b=b.merge(g[keys+['k']],on=keys,how='left'); b['k']=b.k.fillna(1)
        b['p2']=b.pred*b.k
        if shape_only:    # сохранить суточную сумму маршрута — правим только распределение по часам
            s=b.groupby(['route','date']).pred.transform('sum')/b.groupby(['route','date']).p2.transform('sum').replace(0,np.nan)
            b['p2']=b.p2*s.fillna(1)
        res[f]=score(b,'p2')
    return res
for keys in [['route','dt','hour'],['dt','hour'],['route','hour'],['route','dow','hour']]:
    for a in [0.3,0.5,1.0]:
        show(f'   {"×".join(keys)} α={a} (только форма)',corr(keys,a),['F4','F2','F1'])
show('   route×dt×hour α=0.5 (форма и уровень)',corr(['route','dt','hour'],0.5,shape_only=False),['F4','F2','F1'])
print('=== 2. Сезонность по разным годам')
for yrs in [[2024],[2023,2024],[2022,2023,2024],[2019,2022,2023,2024]]:
    def s2(o,months,yrs=yrs): return {m: float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
    show(f'   годы {yrs}',{f:score(fold_pred(f,s2)[0]) for f in ORDER})
def swt(o,months):  # взвешенно: свежие годы весомее (2024:3, 2023:2, 2022:1, 2021:1, 2019:1)
    W={2024:3,2023:2,2022:1,2021:1,2019:1}; ys=[y for y in W if not P.loc[y,[o.month]+months].isna().any()]
    return {m: float(np.average([P.loc[y,m]/P.loc[y,o.month] for y in ys],weights=[W[y] for y in ys])) for m in months}
show('   взвешенно (свежие годы весомее)',{f:score(fold_pred(f,swt)[0]) for f in ORDER})
print('множители ноя/дек от октября:', {k:round(v,4) for k,v in seas(pd.Timestamp('2025-10-31'),[11,12]).items()}, '| 2023–2024:',
      {m: round(float(np.mean([P.loc[y,m]/P.loc[y,10] for y in [2023,2024]])),4) for m in [11,12]}, '| взвеш.:', {k:round(v,4) for k,v in swt(pd.Timestamp('2025-10-31'),[11,12]).items()})
