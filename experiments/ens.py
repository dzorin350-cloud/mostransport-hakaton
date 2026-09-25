import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
def seas(o,months):
    yrs=[y for y in P.index if y<o.year and y!=2020 and not P.loc[y,[o.month]+months].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,o.month] for y in yrs])) for m in months}
rows=[]
for fold in ['F3','F4','F2','F1']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    fac=seas(o,sorted(te.date.dt.month.unique())); hol=build(fr).hol_wd.values==1
    _,c1,p2=forecast(tr,fr,best,seeds=2,fac=fac)
    _,c2,_=forecast(tr,fr,{**best,'loss':'MAE'},seeds=2,fac=fac)
    _,c3,_=forecast(tr,fr,{**best,'loss':'Tweedie','vp':1.5},seeds=2,fac=fac)
    _,c4,_=forecast(tr,fr,{**DEF},seeds=2,fac=fac)              # CatBoost с параметрами по умолчанию (другая глубина/регуляризация)
    _,_,p4=forecast(tr,fr,{**best,'weeks':4},seeds=1,fac=fac); _,_,p8=forecast(tr,fr,{**best,'weeks':8},seeds=1,fac=fac)
    w=best['w']; bl=lambda c,p:np.where(hol,c,w*c+(1-w)*p); sc=lambda p:round(1-wape(y,p),4)
    cands={'1 текущая: CB + профиль 2н':bl(c1,p2),'2 CB + профиль 4н':bl(c1,p4),'3 CB + профиль(2н,4н,8н)':bl(c1,(p2+p4+p8)/3),
           '4 CB(RMSE,MAE) + профиль 2н':bl((c1+c2)/2,p2),'5 CB(RMSE,MAE,Tweedie) + профиль 2н':bl((c1+c2+c3)/3,p2),
           '6 CB(4 вида) + профиль(2н,4н,8н)':bl((c1+c2+c3+c4)/4,(p2+p4+p8)/3),'7 CB(RMSE,MAE)+профиль(2н,4н,8н)':bl((c1+c2)/2,(p2+p4+p8)/3)}
    for k,v in cands.items(): rows.append((fold,k,sc(v)))
    print(fold,{k[:1]:sc(v) for k,v in cands.items()},flush=True)
df=pd.DataFrame(rows,columns=['fold','вариант','скор']).pivot(index='вариант',columns='fold',values='скор')[['F3','F4','F2','F1']]
df['среднее']=df.mean(axis=1).round(4); df['среднее_внутр(F3,F4,F2)']=df[['F3','F4','F2']].mean(axis=1).round(4)
print(df.to_string()); df.to_csv('ens_result.csv')
