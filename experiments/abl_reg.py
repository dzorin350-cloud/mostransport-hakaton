from pipe2 import *
def run(o,s,e,fac_mode='seas'):
    o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values
    mo=sorted(te.date.dt.month.unique()); fac=seas(o,mo) if fac_mode=='seas' else {m:1.0 for m in mo}
    frb=add_reg(build(te[['route','date','hour']])); out={}
    for nm,kw in [('M0 текущая (уровень по всем дням, без режима)',dict(use_reg=False,wd=False)),('M1 уровень по будням, без режима',dict(use_reg=False,wd=True)),('M2 уровень по будням + режим ограничений',dict(use_reg=True,wd=True))]:
        p,_,_=forecast2(tr,frb,best,fac,seeds=2,**kw); out[nm]=p
    return te,y,out
print("=== АБЛЯЦИЯ РЕЖИМА: обучение до 4.10 → прогноз 5–31 октября (режим с 6.09 виден в обучении) ===")
te,y,out=run('2025-10-04','2025-10-05','2025-10-31',fac_mode='none')
m57=np.isin(te.route.values,CUT)&(te.date.dt.dayofweek.values>=5)
for k,p in out.items():
    print(f"{k}: скор {1-wape(y,p):.4f} | ошибка на выходных маршрутов 7 и 50: {np.abs(y-p)[m57].sum()/1000:.1f} тыс. посадок (из {np.abs(y-p).sum()/1000:.1f})")
print("\n=== ПРОВЕРКА, ЧТО НОВАЯ СХЕМА НЕ ЛОМАЕТ ОБЩУЮ КАЧЕСТВО (валидационные периоды, сезонный множитель включён) ===")
rows=[]
for fold in ['F3','F4','F2','F1']:
    o,s,e=FOLDS[fold]; te,y,out=run(o,s,e); rows.append((fold,)+tuple(round(1-wape(y,p),4) for p in out.values())); print(rows[-1],flush=True)
df=pd.DataFrame(rows,columns=['период','M0 текущая','M1 будни','M2 будни+режим']); print(df.to_string(index=False)); print("среднее:",df.drop(columns='период').mean().round(4).to_dict())
