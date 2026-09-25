import optuna, json, time
from pipe import *
optuna.logging.set_verbosity(optuna.logging.WARNING)
INNER=['F3','F4','F2']
def objective(t):
    p=dict(loss=t.suggest_categorical('loss',['RMSE','MAE','Poisson','Tweedie']),iters=t.suggest_int('iters',200,1500,step=100),depth=t.suggest_int('depth',4,10),
      lr=t.suggest_float('lr',0.02,0.2,log=True),l2=t.suggest_float('l2',1,30,log=True),rs=t.suggest_float('rs',0,5),boot=t.suggest_categorical('boot',['MVS','Bayesian','Bernoulli']),
      bt=t.suggest_float('bt',0,5),ss=t.suggest_float('ss',0.5,1.0),vp=t.suggest_float('vp',1.1,1.9),norm_win=t.suggest_categorical('norm_win',[14,21,28,42,56]),
      lvl=t.suggest_categorical('lvl',[14,21,28,35,42,56]),weeks=t.suggest_int('weeks',2,8),w=t.suggest_float('w',0,1))
    s=[score(p,f,1,True)[0] for f in INNER]; t.set_user_attr('folds',[round(x,4) for x in s]); return float(np.mean(s))
st=optuna.create_study(direction='maximize',sampler=optuna.samplers.TPESampler(seed=42,n_startup_trials=15),storage='sqlite:///optuna.db',study_name='cb1',load_if_exists=True)
st.enqueue_trial(dict(loss='RMSE',iters=600,depth=6,lr=0.06,l2=3.0,rs=1.0,boot='MVS',bt=1.0,ss=0.8,vp=1.5,norm_win=28,lvl=28,weeks=4,w=0.5))
t0=time.time()
def cb(study,trial):
    if trial.number%5==0 or trial.value>=study.best_value: print(f"[{time.time()-t0:5.0f}s] trial {trial.number}: {trial.value:.4f} folds={trial.user_attrs['folds']} best={study.best_value:.4f}",flush=True)
st.optimize(objective,timeout=2700,callbacks=[cb])
json.dump(dict(best=st.best_params,value=st.best_value,n=len(st.trials),folds=st.best_trial.user_attrs['folds']),open('best.json','w'),ensure_ascii=False,indent=1)
print("DONE trials",len(st.trials),"best",st.best_value,st.best_params,flush=True)
