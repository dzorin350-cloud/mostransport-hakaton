from harness import *
import pandas as pd
R={}
R['base']=evaluate('baseline')
R['base_s5']=evaluate('baseline 5 seed',seeds=5)
# шум seed: другие два seed
import harness
def eval_seeds(name,sd):
    # временно: сдвиг seed через p (не влияет на кэш-ключи параметров) — отдельный прогон
    return None
print('--- выкидываем по одному признаку')
for f in BASE_FEATS:
    if f=='route': continue
    fs=[x for x in BASE_FEATS if x!=f]; R['-'+f]=evaluate(f'- {f}',feats=fs)
print('--- добавляем признак')
for f in ['dom','month','woy','to_off','from_off','pre2','block','daylen','sunset','dow_off']:
    R['+'+f]=evaluate(f'+ {f}',feats=BASE_FEATS+[f])
print('--- комбинации')
R['dow_hour']=evaluate('+ dow_hour (склейка dow×hour, кат.)',feats=BASE_FEATS+['dow_hour'],cats=('route','dow_hour'),
    extra_fn=lambda df,tr: df.assign(dow_hour=df.dow*24+df.hour), extra_name='dow_hour')
R['route_cat_hour']=evaluate('hour как категория',feats=BASE_FEATS,cats=('route','hour'))
R['route_cat_dow']=evaluate('dow как категория',feats=BASE_FEATS,cats=('route','dow'))
pd.DataFrame(R).T.to_csv('exp1.csv')
