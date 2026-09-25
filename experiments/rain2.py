from rain import *
def clim_factor(b,dates):
    p=PRD[(PRD.index.year>=2022)&(PRD.index.year<=2024)]; f=(1+b*np.minimum(p,20)).clip(0.7,1.1)
    m=f.groupby([f.index.month,f.index.day]).mean()
    return np.array([m.get((d.month,d.day),1.0) for d in dates])
F={'F3':FOLDS['F3'],'F4':FOLDS['F4'],'F2':FOLDS['F2'],'F1':FOLDS['F1']}
rows=[]
for fold,(o,s,e) in F.items():
    o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    fac=seas(o,sorted(te.date.dt.month.unique())); b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
    bb=fit_b(tr); c=clean_grid(tr,1.5,protect_weeks=0)[0]; r=[fold]
    _,cb,pf=forecast(c,fr,best,seeds=2,fac=fac); p7=np.where(hol,cb,w*cb+(1-w)*pf); r.append(round(1-wape(y,p7),4))
    _,cb,pf=forecast(derain(c,bb),fr,best,seeds=2,fac=fac); pr=np.where(hol,cb,w*cb+(1-w)*pf)*clim_factor(bb,te.date)
    r.append(round(1-wape(y,pr),4)); rows.append(r); print(r,flush=True)
df=pd.DataFrame(rows,columns=['период','v7','v7 + дождь (очистка + норма)']); print(df.to_string(index=False)); print(df.iloc[:,1:].mean().round(4).to_dict())
