import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
S=pd.read_parquet('seg_counts.parquet'); S['seg']=S.seg.replace({'кошелёк':'оплата','банк.карта':'оплата','прочее':'оплата'})
days=pd.date_range('2025-01-01','2025-10-31')
grid=pd.MultiIndex.from_product([[r for r in ROUTES],days,range(24)],names=['route','date','hour']).to_frame(index=False)
SG={}
for sg,g in S.groupby('seg'):
    x=grid.merge(g[['route','date','hour','n']],how='left',on=['route','date','hour']); x['boardings']=x.n.fillna(0); SG[sg]=x.drop(columns='n')
print("сегменты:",{k:int(v.boardings.sum()) for k,v in SG.items()}, "| сумма =",int(sum(v.boardings.sum() for v in SG.values())),"vs G",int(G.boardings.sum()))
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
rows=[]
for fold in ['F3','F4','F2','F1']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    fac=seas(o,sorted(te.date.dt.month.unique()))
    _,cbf,pff=forecast(G[G.date<=o],fr,best,seeds=2,fac=fac); hol=build(fr).hol_wd.values==1; w=best['w']
    flat=np.where(hol,cbf,w*cbf+(1-w)*pff)
    cb_s=0; pf_s=0
    for sg,g in SG.items():
        _,c,p=forecast(g[g.date<=o],fr,best,seeds=2,fac=fac); cb_s=cb_s+c; pf_s=pf_s+p
    seg=np.where(hol,cb_s,w*cb_s+(1-w)*pf_s); avg=(flat+seg)/2
    sc=lambda p:round(1-wape(y,p),4); rows.append((fold,sc(flat),sc(seg),sc(avg),sc(cbf),sc(cb_s))); print(rows[-1],flush=True)
df=pd.DataFrame(rows,columns=['период','текущая (общий)','по сегментам билетов','среднее двух','CB общий','CB по сегментам'])
print(df.to_string(index=False)); print("среднее:",df.drop(columns='период').mean().round(4).to_dict())
