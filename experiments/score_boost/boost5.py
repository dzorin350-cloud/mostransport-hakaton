from boost4 import *
_sun={}
def sunday_prof(fold,b,tr):
    if fold in _sun: return _sun[fold]
    o=tr.date.max(); t=tr[tr.date>o-pd.Timedelta(weeks=8)].merge(cal(tr.date.unique()),on='date'); t=t[(t.dow==6)&(t.hol_wd==0)]
    PR=t.groupby(['route','hour']).boardings.median().rename('ps').reset_index()
    _sun[fold]=b.merge(PR,on=['route','hour'],how='left').ps.fillna(0).values*b.f.values; return _sun[fold]
def predict3(fold, w_wd=0.6, w_we=0.6, lam=0.6, we_weeks=None, we_agg='median', night_w=None, hol_w=1.0):
    b, tr = comp(fold, 2, 4, 'median'); pf = b.pf.values.copy()
    if we_weeks:
        b2,_=comp(fold,2,we_weeks,we_agg); we=b.dow.values>=5; pf[we]=b2.pf.values[we]
    w=np.where(b.dow.values>=5,w_we,w_wd)
    if night_w is not None: w=np.where(b.hour.isin([0,1,2,3,4,5,22,23]).values,night_w,w)
    hol=b.hol_wd.values==1
    pred=w*b.cb.values+(1-w)*pf
    pred=np.where(hol, hol_w*b.cb.values+(1-hol_w)*sunday_prof(fold,b,tr), pred)
    bt=beta_v(tr); kr=b.f.values**(lam*(b.route.map(bt).fillna(1.0).values-1))
    y=b.boardings.values; p=pred*kr
    return 1-wape(y,p), (1-wape(y[hol],p[hol]) if hol.any() else np.nan)
def run3(name, **kw):
    r={f:predict3(f,**kw) for f in ORDER}; m4=np.mean([r[f][0] for f in ORDER]); m3=np.mean([r[f][0] for f in ['F4','F2','F1']])
    print(f"{name:<52} "+"  ".join(f"{f}:{r[f][0]:.4f}" for f in ORDER)+f" | ср.4 {m4:.4f} | ср.3 {m3:.4f} | праздн. будни май–июн {r['F4'][1]:.3f}",flush=True)
run3('D2')
run3('D2 + ночь 0,4',night_w=0.4)
run3('D2 + выходные 0,5 + ночь 0,4',w_we=0.5,night_w=0.4)
run3('D2 + выходные 0,4 + профиль вых. 8 нед. mean + ночь 0,4',w_we=0.4,we_weeks=8,we_agg='mean',night_w=0.4)
run3('D2 + выходные 0,5 + профиль вых. 8 нед. mean',w_we=0.5,we_weeks=8,we_agg='mean')
for h in [0.8,0.6,0.4]: run3(f'D2 + праздничные будни: CatBoost {h} + воскресный профиль',hol_w=h)
