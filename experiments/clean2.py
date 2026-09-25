from clean import *
rows=[]
F={'F4':FOLDS['F4'],'F2':FOLDS['F2'],'F1':FOLDS['F1'],'Окт5-31':('2025-10-04','2025-10-05','2025-10-31')}
for fold,(o,s,e) in F.items():
    o=pd.Timestamp(o); tr=G[G.date<=o]; te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
    mo=sorted(te.date.dt.month.unique()); fac=seas(o,mo) if fold!='Окт5-31' else {m:1.0 for m in mo}
    b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1; r=[fold]
    for pw in [0,2,4,8]:
        _,cb,pf=forecast(clean_grid(tr,1.5,protect_weeks=pw)[0],fr,best,seeds=2,fac=fac); r.append(round(1-wape(y,np.where(hol,cb,w*cb+(1-w)*pf)),4))
    rows.append(r); print(r,flush=True)
df=pd.DataFrame(rows,columns=['период','защита 0 нед','2 нед','4 нед','8 нед']); print(df.to_string(index=False)); print(df.iloc[:,1:].mean().round(4).to_dict())
