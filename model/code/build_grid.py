"""Пересобирает data/grid.parquet из исходных labels/*.csv (полная сетка маршрут × дата × час, пропуски = 0)."""
import os, sys, pandas as pd
LBL=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','labels')
L=pd.concat([pd.read_csv(os.path.join(LBL,'labels_day_train.csv'),sep=';'),pd.read_csv(os.path.join(LBL,'labels_day_test.csv'),sep=';')]); L['date']=pd.to_datetime(L['date'])
g=pd.MultiIndex.from_product([[1,5,7,11,12,17,25,26,28,50],pd.date_range('2025-01-01','2025-10-31'),range(24)],names=['route','date','hour']).to_frame(index=False)
G=g.merge(L,how='left',on=['route','date','hour']); G['boardings']=G.boardings.fillna(0)
out=sys.argv[2] if len(sys.argv)>2 else os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','grid.parquet'); G.to_parquet(out); print('grid',G.shape,'->',out)
