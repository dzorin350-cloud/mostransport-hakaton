import pandas as pd, numpy as np
from model import G, ROUTES, cal, wape, D
# Baseline: среднее посадок по (маршрут, день недели, час) за последние 4 недели; праздничные будни -> профиль воскресенья; 1 ноября -> среднее пт и сб
def forecast(tr, dates):
    t=tr[tr.date>tr.date.max()-pd.Timedelta(weeks=4)].copy(); t['dow']=t.date.dt.dayofweek
    prof=t.groupby(['route','dow','hour']).boardings.mean().rename('p').reset_index()
    F=pd.MultiIndex.from_product([ROUTES,pd.to_datetime(dates),range(24)],names=['route','date','hour']).to_frame(index=False).merge(cal(dates),on='date')
    F['pdow']=np.where(F.hol_wd==1,6,F.dow)
    F=F.merge(prof.rename(columns={'dow':'pdow'}),on=['route','pdow','hour'],how='left')
    n1=F.date.eq('2025-11-01')
    if n1.any():
        for d_ in (4,5): pass
        pf=prof.pivot_table(index=['route','hour'],columns='dow',values='p')
        F.loc[n1,'p']=[(pf.loc[(r,h),4]+pf.loc[(r,h),5])/2 for r,h in zip(F[n1].route,F[n1].hour)]
    F['p']=F.p.fillna(0); return F[['route','date','hour','p']]
if __name__=='__main__':
    print("Бэктест (обучение до даты -> прогноз на 2 мес. вперёд), score=1-WAPE:")
    for nm,e,s,t in [('Сен–Окт (обуч. до 31.08)','2025-08-31','2025-09-01','2025-10-31'),('Июл–Авг (обуч. до 30.06)','2025-06-30','2025-07-01','2025-08-31'),('Мар–Апр (обуч. до 28.02)','2025-02-28','2025-03-01','2025-04-30')]:
        tr=G[G.date<=e]; te=G[(G.date>=s)&(G.date<=t)]
        F=forecast(tr,pd.date_range(s,t)); m=te.merge(F,on=['route','date','hour'])
        print(f"  {nm}: {1-wape(m.boardings.values,m.p.values):.4f}")
    # пример организаторов на тех же Сен–Окт: константы по маршрутам из test_submission
    ref=pd.read_csv(D+'test_submission.csv',sep=';'); c=ref.groupby('route').prediction.first()
    te=G[(G.date>='2025-09-01')&(G.date<='2025-10-31')]
    print("  (для сравнения) константы из test_submission на Сен–Окт:",round(1-wape(te.boardings.values,te.route.map(c).fillna(0).values),4))
    # финал
    F=forecast(G,pd.date_range('2025-11-01','2025-12-31')); F=F.rename(columns={'p':'prediction'})
    r5=pd.DataFrame([(5,d,h,0.0) for d in pd.date_range('2025-11-01','2025-12-31') for h in range(24)],columns=F.columns)
    S=pd.concat([F,r5]); S['date']=S.date.dt.strftime('%Y-%m-%d'); S['prediction']=S.prediction.round(1).clip(lower=0)
    ref=pd.read_csv(D+'test_submission.csv',sep=';'); S=ref[['route','date','hour']].merge(S,on=['route','date','hour'],how='left')
    assert len(S)==14640 and S.prediction.notna().all()
    S.to_csv(D+'submission_baseline.csv',sep=';',index=False); print("saved submission_baseline.csv",S.shape); print(S.head(3).to_string(index=False))
