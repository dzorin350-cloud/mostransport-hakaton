import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
from catboost import CatBoostRegressor
import os; D=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","data")+"/"
G=pd.read_parquet(D+'grid.parquet'); G=G[G.route!=5].copy()
ROUTES=sorted(G.route.unique())
# ---- calendar (RU 2025 production calendar) ----
DAYOFF=set(pd.date_range('2025-01-01','2025-01-08'))|{pd.Timestamp('2025-03-08'),pd.Timestamp('2025-03-09')}|set(pd.date_range('2025-05-01','2025-05-04'))|set(pd.date_range('2025-05-08','2025-05-11'))|set(pd.date_range('2025-06-12','2025-06-15'))|{pd.Timestamp(x) for x in ['2025-11-02','2025-11-03','2025-11-04','2025-12-31']}
def cal(dates):
    c=pd.DataFrame({'date':pd.to_datetime(dates)}); c['dow']=c.date.dt.dayofweek
    off=c.date.isin(DAYOFF)|(c.dow>=5)
    if True: off=off&~c.date.eq(pd.Timestamp('2025-11-01'))   # 1 Nov 2025 = working Saturday
    c['off']=off.astype(int)
    c['hol_wd']=(c.date.isin(DAYOFF)&(c.dow<5)).astype(int)
    nxt=c.date.map(lambda d:int((d+pd.Timedelta(days=1)) in DAYOFF or (d+pd.Timedelta(days=1)).dayofweek>=5))
    prv=c.date.map(lambda d:int((d-pd.Timedelta(days=1)) in DAYOFF or (d-pd.Timedelta(days=1)).dayofweek>=5))
    c['pre']=((nxt==1)&(c.off==0)).astype(int); c['post']=((prv==1)&(c.off==0)).astype(int)
    c['dom']=c.date.dt.day
    # длина светового дня в Москве (55.75° с. ш.), ч — астрономия, известна заранее
    doy=c.date.dt.dayofyear.values; lat=np.radians(55.75)
    decl=np.radians(23.44)*np.sin(2*np.pi*(284+doy)/365)
    ha=np.degrees(np.arccos(np.clip(-np.tan(lat)*np.tan(decl),-1,1)))
    c['daylen']=2*ha/15
    return c
def wape(y,p): return np.abs(y-p).sum()/y.sum()
FEATS=['route','hour','dow','off','hol_wd','pre','post']
def build(df):
    c=cal(df.date.unique()); return df.merge(c,on='date')
def level_norm(df):
    d=df.groupby(['route','date']).boardings.sum().unstack(0)
    L=d.rolling(28,center=True,min_periods=10).mean()
    return L.stack().rename('L').reset_index()
def fit_shape(tr,loss='MAE',it=600,seed=0):
    tr=build(tr).merge(level_norm(tr),on=['route','date'])
    tr=tr[tr.L>0].dropna(subset=['L']); tr['t']=tr.boardings/tr.L; w=tr.L
    m=CatBoostRegressor(loss_function=loss,iterations=it,depth=6,learning_rate=0.06,cat_features=['route'],random_seed=seed,verbose=0,thread_count=10)
    X=tr[FEATS].copy(); X['route']=X.route.astype(int)
    m.fit(X,tr.t,sample_weight=w); return m
def pred_shape(m,te):
    te=build(te); X=te[FEATS].copy(); X['route']=X.route.astype(int); return np.clip(m.predict(X),0,None),te
def profile(tr,weeks,agg):
    t=build(tr[tr.date>tr.date.max()-pd.Timedelta(weeks=weeks)]); t=t[(t.hol_wd==0)]
    return t.groupby(['route','dow','hour']).boardings.agg(agg).rename('p').reset_index()
def run_fold(name,train_end,test_start,test_end):
    tr=G[G.date<=train_end]; te=G[(G.date>=test_start)&(G.date<=test_end)].copy()
    Ltrue=te.groupby('route').boardings.sum()/te.date.nunique()/1   # mean daily per route in test
    last=tr[tr.date>tr.date.max()-pd.Timedelta(days=28)]; Lfc=last.groupby('route').boardings.sum()/28
    res={}; y=te.boardings.values
    res['B0 const(mean of train)']=(wape(y,np.full(len(y),tr.boardings.mean())),None)
    for nm,wk,agg in [('B1 profile mean 4w',4,'mean'),('B2 profile median 8w',8,'median')]:
        pr=te.merge(build(te[['date']].drop_duplicates()),on='date').merge(profile(tr,wk,agg),on=['route','dow','hour'],how='left').fillna({'p':0})
        pr=pr.set_index(te.index) if len(pr)==len(te) else pr
        p=pr.p.values
        # oracle level: rescale per route to true total
        s=(te.assign(p=p).groupby('route').apply(lambda g:g.boardings.sum()/max(g.p.sum(),1e-9)))
        po=p*te.route.map(s).values
        res[nm]=(wape(y,p),wape(y,po))
    for loss in ['MAE','RMSE']:
        ps=np.mean([pred_shape(fit_shape(tr,loss,seed=s),te)[0] for s in range(2)],axis=0)
        p=ps*te.route.map(Lfc).values; po=ps*te.route.map(Ltrue).values
        res[f'CB {loss} shape*L']=(wape(y,p),wape(y,po))
        if loss=='MAE': pcb,pcbo=p,po
    # blend CB + B1
    pr=te.merge(build(te[['date']].drop_duplicates()),on='date').merge(profile(tr,4,'mean'),on=['route','dow','hour'],how='left').fillna({'p':0}); p1=pr.p.values
    res['blend CB_MAE+B1']=(wape(y,0.5*pcb+0.5*p1),None)
    print(f"\n=== {name}: train<= {train_end}, test {test_start}..{test_end}  (WAPE-score = 1-WAPE)")
    print(f"level err by route (fc/true-1): "+", ".join(f"{r}:{Lfc[r]/Ltrue[r]-1:+.0%}" for r in ROUTES))
    print(pd.DataFrame({k:{'score(naive level)':1-v[0],'score(oracle level)':(1-v[1]) if v[1] is not None else np.nan} for k,v in res.items()}).T.round(4).to_string())
    return res
if __name__=='__main__':
  run_fold('F1 autumn','2025-08-31','2025-09-01','2025-10-31')
  run_fold('F2 summer','2025-06-30','2025-07-01','2025-08-31')
  run_fold('F3 spring(stable, has holidays)','2025-02-28','2025-03-01','2025-04-30')
