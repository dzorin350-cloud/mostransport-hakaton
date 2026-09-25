from clean import *
H=pd.read_parquet('/Users/denis/Documents/Данные хакатон Мос Транспорт/external/weather_hourly_2022_2025-10.parquet'); H['date']=H.time.dt.normalize()
PRD=H[(H.time.dt.hour>=6)&(H.time.dt.hour<=21)].groupby('date').precipitation.sum().rename('pr')
def fit_b(tr):
    d=tr.groupby(['route','date']).boardings.sum().reset_index(); d['dt']=dtype(d.date); d=d[d.dt!='hol']
    d['exp']=d.groupby(['route','dt']).boardings.transform(lambda s:s.rolling(11,center=True,min_periods=3).median())
    n=d.groupby('date').apply(lambda g:g.boardings.sum()/g.exp.sum()).rename('r').reset_index().merge(PRD.reset_index(),on='date')
    n=n[(n.r>0.75)&(n.r<1.33)]; x=np.minimum(n.pr,20); b=np.polyfit(x,n.r,1)[0]; return b
def derain(tr,b):
    t=tr.merge(PRD.reset_index(),on='date',how='left'); f=1+b*np.minimum(t.pr.fillna(0),20)
    t['boardings']=t.boardings/np.clip(f,0.7,1.1); return t[['route','date','hour','boardings']]
if __name__=='__main__':
    F={'F3':FOLDS['F3'],'F4':FOLDS['F4'],'F2':FOLDS['F2'],'F1':FOLDS['F1'],'Окт5-31':('2025-10-04','2025-10-05','2025-10-31')}
    rows=[]
    for fold,(o,s,e) in F.items():
        o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
        mo=sorted(te.date.dt.month.unique()); fac=seas(o,mo) if fold!='Окт5-31' else {m:1.0 for m in mo}
        b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1
        bb=fit_b(tr); c=clean_grid(tr,1.5,protect_weeks=0)[0]; r=[fold,round(bb,4)]
        for nm,trx in [('v7',c),('v7+дождь',derain(c,bb))]:
            _,cb,pf=forecast(trx,fr,best,seeds=2,fac=fac); r.append(round(1-wape(y,np.where(hol,cb,w*cb+(1-w)*pf)),4))
        rows.append(r); print(r,flush=True)
    df=pd.DataFrame(rows,columns=['период','b (на 1 мм)','v7','v7 + очистка дождя']); print(df.to_string(index=False)); print(df.iloc[:,2:].mean().round(4).to_dict())
