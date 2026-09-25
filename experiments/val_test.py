import optuna, json
from pipe import *
optuna.logging.set_verbosity(optuna.logging.ERROR)
st=optuna.load_study(study_name='cb1',storage='sqlite:///optuna.db'); best=dict(DEF); best.update(st.best_params)
print("параметры (Optuna, проба",st.best_trial.number,"из",len(st.trials),", inner-скор",round(st.best_value,4),"):",{k:(round(v,3) if isinstance(v,float) else v) for k,v in st.best_params.items()},flush=True)
o=pd.Timestamp('2025-08-31'); months=[9,10]
def seas_only(origin,months):
    Y=origin.year; base=origin.month
    yrs=[y for y in P.index if y<Y and y!=2020 and not P.loc[y,[base]+list(months)].isna().any()]
    return {m:float(np.mean([P.loc[y,m]/P.loc[y,base] for y in yrs])) for m in months}
fac_s=seas_only(o,months); fac_m=factors(o,months); fac_1={m:1.0 for m in months}
print("множители уровня (данные города ≤ авг 2025): только сезонность",{k:round(v,3) for k,v in fac_s.items()},"| сезонность+YoY",{k:round(float(v),3) for k,v in fac_m.items()},flush=True)
tr=G[G.date<=o]; te=G[(G.date>='2025-09-01')&(G.date<='2025-10-31')]; y=te.boardings.values; fr=te[['route','date','hour']]
res=[]
for pn,p in [('по умолчанию',DEF),('после Optuna',best)]:
    for fn,fac in [('без поправки',fac_1),('поправка: только сезонность (честный)',fac_s),('поправка: сезонность+YoY',fac_m)]:
        out,cb,pf=forecast(tr,fr,p,seeds=5,fac=fac)
        res.append((pn,fn,1-wape(y,out),1-wape(y,cb),1-wape(y,pf)))
        print(res[-1][:2],[round(x,4) for x in res[-1][2:]],flush=True)
df=pd.DataFrame(res,columns=['параметры','уровень','смесь','CatBoost','профиль']).round(4); df.to_csv('val_test_result.csv',index=False)
print("\nИТОГ: обучение на train (до 31.08) → проверка на test (сен–окт), score = 1 − WAPE"); print(df.to_string(index=False))
