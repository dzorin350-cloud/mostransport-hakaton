import json, itertools
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
D_={}
for fold in ['F3','F4','F2','F1']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; fr=te[['route','date','hour']]
    fac=seas(o,sorted(te.date.dt.month.unique())); _,cb,pf=forecast(tr,fr,best,seeds=2,fac=fac)
    b=build(fr); D_[fold]=dict(y=te.boardings.values,cb=cb,pf=pf,hol=b.hol_wd.values==1,we=(b.dow.values>=5))
ws=[0,.2,.4,.6,.8,1]
def sc(f,ww,wk):
    d=D_[f]; w=np.where(d['we'],ww,wk); p=np.where(d['hol'],d['cb'],w*d['cb']+(1-w)*d['pf']); return 1-wape(d['y'],p)
inner=['F3','F4','F2']
grid=pd.DataFrame([(a,b,np.mean([sc(f,a,b) for f in inner])) for a in ws for b in ws],columns=['w_выходные','w_будни','inner']).sort_values('inner',ascending=False)
print("топ-5 по внутренним периодам:"); print(grid.head(5).round(4).to_string(index=False))
a,b=grid.iloc[0].w_выходные,grid.iloc[0].w_будни
print(f"\nвыбор на внутренних периодах: w выходные={a}, w будни={b}")
print("текущее (w=0,416 везде): внутр.",round(np.mean([sc(f,.416,.416) for f in inner]),4),"| test F1",round(sc('F1',.416,.416),4))
print("раздельные веса        : внутр.",round(np.mean([sc(f,a,b) for f in inner]),4),"| test F1",round(sc('F1',a,b),4))
