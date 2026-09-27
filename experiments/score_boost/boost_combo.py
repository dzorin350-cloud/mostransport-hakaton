from boost_lib35 import *
F3=['F4','F2','F1']
LM={f:level_model(f)[0] for f in F3}
PREV={'F4':'F3','F2':'F4','F1':'F2'}
def pred_beta(f,lam):
    b,tr=B[f]; bt=beta_route(tr); be=b.route.map(lambda r:1+lam*(bt.get(r,1)-1)).clip(0,2); return b.pred*(b.f**(be-1))
def with_level(b,p,f,a):
    x=b.assign(p=p).merge(LM[f],on=['route','date'],how='left'); day=x.groupby(['route','date']).p.transform('sum')
    return x.p*((x.tot_hat/day.replace(0,np.nan)).fillna(1)**a)
def with_shape(b,p,f,a,keys=['route','hour']):
    bp=B[PREV[f]][0]; g=bp.groupby(keys).agg(y=('boardings','sum'),q=('pred','sum')).reset_index(); g['k']=1+a*((g.y/g.q).clip(0.8,1.25)-1)
    x=b.assign(p=p.values).merge(g[keys+['k']],on=keys,how='left'); x['p2']=x.p*x.k.fillna(1)
    s=x.groupby(['route','date']).p.transform('sum')/x.groupby(['route','date']).p2.transform('sum'); return x.p2*s
for lam in [0.3,0.5]:
    show(f'β λ={lam}',{f:score(B[f][0].assign(p2=pred_beta(f,lam).values),'p2') for f in F3},F3)
    for a in [0.2,0.3]:
        show(f'β λ={lam} + модель уровня α={a}',{f:score(B[f][0].assign(p2=with_level(B[f][0],pred_beta(f,lam),f,a).values),'p2') for f in F3},F3)
    show(f'β λ={lam} + коррекция формы route×hour α=0.3',{f:score(B[f][0].assign(p2=with_shape(B[f][0],pred_beta(f,lam),f,0.3).values),'p2') for f in F3},F3)
# β для ноября–декабря (старт 31.10, вся история)
import harness
tr,_=harness.fold_data('F1',CLEAN)  # заглушка для импорта
from clean import clean_grid, G
trF,_=clean_grid(G.copy(),1.5,protect_weeks=0)
bt=beta_route(trF); print('β маршрутов для ноября–декабря:',{k:round(v,2) for k,v in bt.items()})
f=seas(pd.Timestamp('2025-10-31'),[11,12]); print('множители маршрутов при λ=0.5:',{r:(round(f[11]**(1+0.5*(v-1)),4),round(f[12]**(1+0.5*(v-1)),4)) for r,v in bt.items()})
