import json
from pipe import *
best=dict(DEF); best.update(json.load(open('best_params_final.json'))['params'])
SETS={'A все годы (2019,2021–2024)':[2019,2021,2022,2023,2024],'B с 2022 (2022–2024)':[2022,2023,2024],'C 2023–2024':[2023,2024],'D только 2024':[2024]}
def fac(o,months,yrs):
    base=o.month; return {m:float(np.mean([P.loc[y,m]/P.loc[y,base] for y in yrs])) for m in months}
print("Коэффициенты и разброс по годам (отдельные годы):")
for base,ms,lab in [(8,[9,10],'от августа к сент/окт'),(10,[11,12],'от октября к ноя/дек')]:
    t=pd.DataFrame({y:{m:P.loc[y,m]/P.loc[y,base] for m in ms} for y in [2019,2021,2022,2023,2024]}).T
    print(lab); print(t.round(3).T.to_string()); print("  std по годам A:",t.std().round(3).to_dict(),"| std с 2022:",t.loc[[2022,2023,2024]].std().round(3).to_dict())
    for k,v in SETS.items(): print("  ",k,{m:round(x,3) for m,x in fac(pd.Timestamp(f'2025-{base:02d}-28'),ms,[y for y in v]).items()})
res=[]
for fold in ['F1','F4','F2','F3']:
    o,s,e=FOLDS[fold]; o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    mo=sorted(te.date.dt.month.unique()); _,cb,pf=forecast(tr,fr,best,seeds=2,fac={m:1.0 for m in mo})
    b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); base=np.where(b.hol_wd.values==1,cb,w*cb+(1-w)*pf)
    r=[fold]
    for k,v in SETS.items():
        f=te.date.dt.month.map(fac(o,mo,v)).values; r.append(round(1-wape(y,base*f),4))
    res.append(r)
df=pd.DataFrame(res,columns=['период']+list(SETS)); df.loc['среднее']=['']+[round(float(df[c].mean()),4) for c in SETS]
print("\nСкор на валидации при разных наборах лет для сезонного коэффициента:"); print(df.to_string(index=False))
