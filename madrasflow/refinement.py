"""A single baseline-anchored challenger; settings selected on March 15–21 only."""
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from .storage import connection,literal,write_json
from .forecast import metrics

COLS=['route_code','hour','is_weekend','historical_mean','recent_mean','lag_1','lag_7','history_days']

def cached_features(path,out):
    con=connection()
    con.execute(f'CREATE TEMP VIEW raw AS SELECT * FROM read_parquet({literal(path)})')
    con.execute('''CREATE TEMP TABLE dense AS SELECT d.date,h.hour,d.route_id series_id,
        cast(isodow(d.date)>=6 AS INTEGER) is_weekend,coalesce(r.passengers,0) passengers
        FROM (SELECT DISTINCT date,route_id FROM raw WHERE date BETWEEN DATE '2026-03-02' AND DATE '2026-03-31') d
        CROSS JOIN range(24) h(hour) LEFT JOIN raw r ON r.date=d.date AND r.route_id=d.route_id AND r.hour=h.hour''')
    con.execute('''CREATE TEMP TABLE f AS SELECT *,
        avg(passengers) OVER(PARTITION BY series_id,hour,is_weekend ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) comparable,
        count(*) OVER(PARTITION BY series_id,hour,is_weekend ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) history_days,
        avg(passengers) OVER(PARTITION BY series_id,hour ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) broad,
        avg(passengers) OVER(PARTITION BY hour,is_weekend ORDER BY date RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 DAY PRECEDING) network,
        avg(passengers) OVER(PARTITION BY series_id,hour ORDER BY date RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING) recent
        FROM dense''')
    con.execute(f'''COPY (SELECT f.date,f.hour,f.series_id,f.is_weekend,f.passengers,f.history_days,
        coalesce(comparable,broad,network,0) historical_mean,
        coalesce(recent,comparable,broad,network,0) recent_mean,a.passengers lag_1,b.passengers lag_7
        FROM f LEFT JOIN dense a ON a.series_id=f.series_id AND a.hour=f.hour AND a.date=f.date-1
        LEFT JOIN dense b ON b.series_id=f.series_id AND b.hour=f.hour AND b.date=f.date-7)
        TO {literal(out)} (FORMAT PARQUET, COMPRESSION ZSTD)''')
    con.close()

def run_refinement(data='data',output='artifacts/refinement'):
    data,output=Path(data),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    cached_features(data/'hourly.parquet',output/'features.parquet')
    con=connection()
    frame=con.execute(f'SELECT * FROM read_parquet({literal(output/"features.parquet")})').fetchdf()
    con.close()
    frame['date']=pd.to_datetime(frame.date)
    def encode(df,categories):
        df=df.copy();df['route_code']=pd.Categorical(df.series_id,categories=categories)
        return df
    def matrix(df,labels=False):
        return xgb.DMatrix(df[COLS],label=df.passengers if labels else None,enable_categorical=True,
            base_margin=np.log(np.maximum(df.historical_mean.to_numpy(),0.01)),nthread=4)
    params={'objective':'count:poisson','eval_metric':'mae','tree_method':'hist',
        'max_depth':3,'eta':0.03,'min_child_weight':50,'lambda':20,'seed':42,'nthread':4}
    cats=sorted(frame.loc[frame.date<=pd.Timestamp('2026-03-14'),'series_id'].unique())
    train=encode(frame[(frame.date>=pd.Timestamp('2026-03-07'))&(frame.date<=pd.Timestamp('2026-03-14'))],cats)
    val=encode(frame[(frame.date>=pd.Timestamp('2026-03-15'))&(frame.date<=pd.Timestamp('2026-03-21'))],cats)
    print('Training one baseline-anchored XGBoost challenger',flush=True)
    model=xgb.train(params,matrix(train,True),num_boost_round=80,evals=[(matrix(val,True),'validation')],
                    early_stopping_rounds=10,verbose_eval=False)
    rounds=model.best_iteration+1;model=model[:rounds]
    def predict(model,df):
        return np.where(df.route_code.isna(),df.historical_mean,np.maximum(model.predict(matrix(df)),0))
    vp=predict(model,val)
    validation={'baseline':metrics(val.passengers,val.historical_mean),'anchored_xgboost':metrics(val.passengers,vp)}
    busy=val.hour.isin([7,8,9,17,18,19])
    peak={'baseline':metrics(val.loc[busy,'passengers'],val.loc[busy,'historical_mean']),
          'anchored_xgboost':metrics(val.loc[busy,'passengers'],vp[busy])}
    champion='anchored_xgboost' if (validation['anchored_xgboost']['mae']<validation['baseline']['mae']
        and peak['anchored_xgboost']['mae']<=peak['baseline']['mae']) else 'baseline'
    print('Validation selected:',champion,'rounds:',rounds,flush=True)
    cats=sorted(frame.loc[frame.date<=pd.Timestamp('2026-03-28'),'series_id'].unique())
    fit=encode(frame[(frame.date>=pd.Timestamp('2026-03-07'))&(frame.date<=pd.Timestamp('2026-03-28'))],cats)
    final=xgb.train(params,matrix(fit,True),num_boost_round=rounds)
    audit=encode(frame[(frame.date>=pd.Timestamp('2026-03-29'))&(frame.date<=pd.Timestamp('2026-03-31'))],cats)
    ap=predict(final,audit)
    scores={'baseline':metrics(audit.passengers,audit.historical_mean),'anchored_xgboost':metrics(audit.passengers,ap)}
    report={'method':'XGBoost count corrections anchored at log historical mean','validation':validation,
        'busy_validation':peak,'selected_on_validation':champion,'selected_rounds':rounds,
        'fresh_audit_dates':['2026-03-29','2026-03-30','2026-03-31'],'fresh_audit':scores,
        'selection_rule':'Improve validation MAE without worsening busy-hour MAE; no selection using audit scores',
        'original_test_not_reused':'March22–28 had already been inspected; revised audit is March29–31, only three days',
        'limitation':'Boarding forecasts only; does not independently validate crowding or destinations'}
    write_json(output/'metrics.json',report)
    write_json(output/'model_metadata.json',{'categories':cats,'champion':champion,'rounds':rounds,'training_cutoff':'2026-03-28'})
    final.save_model(output/'model.ubj')
    print(report,flush=True)
    return report
