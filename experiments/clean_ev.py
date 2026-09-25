from clean import *
from events import event_mask
def impute_hourly(tr,mask):
    """строки mask заменить медианой того же (маршрут, тип дня, час) по чистым дням в окне ±5 таких же дней"""
    t=tr.copy(); t['dt']=dtype(t.date); t['m']=mask.values; t=t.sort_values(['route','dt','hour','date'])
    v=t.boardings.where(~t.m)
    t['imp']=v.groupby([t.route,t.dt,t.hour]).transform(lambda s:s.rolling(11,center=True,min_periods=3).median().ffill().bfill())
    t['boardings']=np.where(t.m&t.imp.notna(),t.imp,t.boardings)
    return t.sort_values(['route','date','hour'])[['route','date','hour','boardings']].reset_index(drop=True)
def clean_events(tr): return impute_hourly(tr,event_mask(tr)[0].reindex(tr.index))
def clean_both(tr): return clean_grid(clean_events(tr),1.5,protect_weeks=0)[0]
if __name__=='__main__':
    F={'F3':FOLDS['F3'],'F4':FOLDS['F4'],'F2':FOLDS['F2'],'F1':FOLDS['F1'],'Окт5-31':('2025-10-04','2025-10-05','2025-10-31')}
    rows=[]
    for fold,(o,s,e) in F.items():
        o=pd.Timestamp(o); tr=G[G.date<=o].reset_index(drop=True); te=G[(G.date>=s)&(G.date<=e)]; y=te.boardings.values; fr=te[['route','date','hour']]
        mo=sorted(te.date.dt.month.unique()); fac=seas(o,mo) if fold!='Окт5-31' else {m:1.0 for m in mo}
        b=build(fr); w=np.where(b.dow.values>=5,0.8,0.6); hol=b.hol_wd.values==1; r=[fold]
        for nm,trx in [('v4',tr),('авто (v7)',clean_grid(tr,1.5,protect_weeks=0)[0]),('события',clean_events(tr)),('события+авто',clean_both(tr))]:
            _,cb,pf=forecast(trx,fr,best,seeds=2,fac=fac); r.append(round(1-wape(y,np.where(hol,cb,w*cb+(1-w)*pf)),4))
        rows.append(r); print(r,flush=True)
    df=pd.DataFrame(rows,columns=['период','v4','авто (v7)','события','события+авто']); print(df.to_string(index=False)); print(df.iloc[:,1:].mean().round(4).to_dict())
