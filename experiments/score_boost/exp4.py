from harness import *
import harness
tr,_=fold_data('F1',dict(thr=1.5,protect_weeks=0)); print('часов-выбросов (k=2) в обучении сен–окт:',clean_hours(tr,2).attrs['n_bad'],'из',len(tr))
for k in [1.8,2.5,3.0]: evaluate(f'+ очистка часов k={k}',clean_cfg=dict(thr=1.5,protect_weeks=0,hour_k=k))
print('--- ансамбль вариантов формы (среднее долей CatBoost)')
def ens(name, variants, **kw):
    # усредняем долю CatBoost по вариантам признаков, остальное как в базе
    orig=harness.cb_share
    def cbs(fold,clean_cfg,feats,cats,p,seed,extra_fn=None,extra_name=None):
        return np.mean([orig(fold,clean_cfg,v,['route'],p,seed) for v in variants],axis=0)
    harness.cb_share=cbs
    try: return evaluate(name,**kw)
    finally: harness.cb_share=orig
B=BASE_FEATS
ens('ансамбль: база + световой день',[B,B+['daylen']])
ens('ансамбль: база + месяц',[B,B+['month']])
ens('ансамбль: база + световой день + месяц',[B,B+['daylen'],B+['month']])
ens('ансамбль: база + световой день + месяц + день месяца',[B,B+['daylen'],B+['month'],B+['dom']])
ens('ансамбль (база+свет) + профиль 4 нед. медиана',[B,B+['daylen']],weeks=4,prof_agg='median')
print('--- гиперпараметры')
evaluate('depth=6',p=dict(depth=6)); evaluate('depth=10',p=dict(depth=10)); evaluate('iters=1500 lr/2',p=dict(iters=1600,lr=0.0245))
