"""Weekday/weekend pooled XGBoost and a past-only historical benchmark."""
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from .storage import connection, literal, write_json, load_json

FEATURES=['route_code','hour','is_weekend','historical_mean','recent_mean','lag_1','lag_7','history_days']

def prepare_frame(path, label_kind='boardings'):
    con=connection()
    if label_kind=='boardings':
        con.execute(f'CREATE TEMP VIEW raw AS SELECT * FROM read_parquet({literal(path)})')
        df=con.execute('''SELECT d.date,h.hour,d.route_id series_id,coalesce(r.passengers,0) passengers
            FROM (SELECT DISTINCT date,route_id FROM raw) d CROSS JOIN range(0,24) h(hour)
            LEFT JOIN raw r ON r.date=d.date AND r.route_id=d.route_id AND r.hour=h.hour''').fetchdf()
    else:
        df=con.execute(f'SELECT date,hour,series_id,passengers FROM read_parquet({literal(path)})').fetchdf()
    con.close()
    df['date']=pd.to_datetime(df['date'])
    # Incomplete external month-boundary duty spillovers must not become target labels.
    df=df[(df.date>=pd.Timestamp('2026-03-02')) & (df.date<=pd.Timestamp('2026-03-31'))].copy()
    df['is_weekend']=(df.date.dt.dayofweek>=5).astype('int8')
    return df.sort_values(['series_id','hour','date']).reset_index(drop=True)

def features(history, target, categories):
    """Every feature is computed from the supplied history, never target labels."""
    if len(history) and history.date.max()>=target.date.min():
        raise ValueError('History overlaps target date: future information would leak')
    keys=['series_id','hour']
    h=history.copy()
    dt=target.date.min()
    fallback=h.groupby(['hour','is_weekend']).passengers.mean()
    means=h.groupby(keys+['is_weekend']).passengers.agg(['mean','count']).rename(columns={'mean':'historical_mean','count':'history_days'})
    recent=h[h.date>=dt-pd.Timedelta(days=7)].groupby(keys).passengers.mean().rename('recent_mean')
    x=target[['date','series_id','hour','is_weekend']].copy().join(means,on=keys+['is_weekend']).join(recent,on=keys)
    for lag in [1,7]:
        past=h[h.date==dt-pd.Timedelta(days=lag)].set_index(keys).passengers.rename(f'lag_{lag}')
        x=x.join(past,on=keys)
    broad=h.groupby(keys).passengers.mean()
    fill=x.set_index(keys).index.map(broad)
    global_fill=pd.MultiIndex.from_frame(x[['hour','is_weekend']]).map(fallback)
    x['historical_mean']=x['historical_mean'].fillna(pd.Series(fill,index=x.index)).fillna(pd.Series(global_fill,index=x.index)).fillna(0)
    x['history_days']=x['history_days'].fillna(0)
    x['recent_mean']=x['recent_mean'].fillna(x.historical_mean)
    x['route_code']=pd.Categorical(x.series_id,categories=categories)
    return x

def training_features(frame, cutoff, categories, minimum_history=5):
    days=sorted(frame.loc[frame.date<=pd.Timestamp(cutoff),'date'].unique())
    chunks=[]
    for day in days[minimum_history:]:
        target=frame[frame.date==day]
        x=features(frame[frame.date<day],target,categories)
        x['passengers']=target.passengers.values
        chunks.append(x)
    if not chunks: raise ValueError('Insufficient training history')
    return pd.concat(chunks,ignore_index=True)

def matrix(frame, labels=False):
    return xgb.DMatrix(frame[FEATURES],label=frame.passengers if labels else None,
                       enable_categorical=True,nthread=4)

def metrics(actual,pred):
    actual,pred=np.asarray(actual),np.asarray(pred)
    total=float(actual.sum())
    return {'rows':len(actual),'actual_passengers':total,
        'mae':float(np.abs(pred-actual).mean()),
        'wape':float(np.abs(pred-actual).sum()/total) if total else None,
        'mean_signed_error':float((pred-actual).mean()),
        'underpredicted_passengers':float(np.maximum(actual-pred,0).sum())}

def evaluate(model,frame,days,categories):
    outputs=[]
    for day in days:
        target=frame[frame.date==day]
        x=features(frame[frame.date<day],target,categories)
        pred=model.predict(matrix(x))
        # Routes absent from the fitted model receive the explicit historical fallback.
        pred=np.where(x.route_code.isna(),x.historical_mean,pred)
        out=target.copy()
        out['baseline']=x.historical_mean.values
        out['xgboost']=np.maximum(0,pred)
        out['history_days']=x.history_days.values
        outputs.append(out)
    return pd.concat(outputs,ignore_index=True)

def train_and_evaluate(path,output,label_kind='boardings',rounds=100):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    df=prepare_frame(path,label_kind)
    train_end=pd.Timestamp('2026-03-14')
    validation_end=pd.Timestamp('2026-03-21')
    test_end=pd.Timestamp('2026-03-28')
    categories=sorted(df.loc[df.date<=train_end,'series_id'].unique())
    train=training_features(df,train_end,categories)
    valdays=sorted(df.loc[(df.date>train_end)&(df.date<=validation_end),'date'].unique())
    valparts=[]
    for day in valdays:
        target=df[df.date==day]
        x=features(df[df.date<day],target,categories)
        x['passengers']=target.passengers.values
        valparts.append(x)
    val=pd.concat(valparts,ignore_index=True)
    params={'objective':'count:poisson','eval_metric':'mae','tree_method':'hist',
            'max_depth':6,'eta':0.08,'min_child_weight':20,'lambda':5,
            'subsample':0.9,'colsample_bytree':1.0,'seed':42,'nthread':4}
    print(f'Training {label_kind}: {len(train):,} examples; {len(categories):,} series',flush=True)
    candidate=xgb.train(params,matrix(train,True),num_boost_round=rounds,
        evals=[(matrix(val,True),'validation')],early_stopping_rounds=15,verbose_eval=False)
    selected_rounds=candidate.best_iteration+1
    candidate=candidate[:selected_rounds]
    valpred=evaluate(candidate,df,valdays,categories)
    valmetrics={name:metrics(valpred.passengers,valpred[name]) for name in ['baseline','xgboost']}
    champion='xgboost' if valmetrics['xgboost']['mae']<valmetrics['baseline']['mae'] else 'baseline'
    # Freeze settings using validation; refit once through March 21, then keep weights fixed for test.
    categories=sorted(df.loc[df.date<=validation_end,'series_id'].unique())
    finaltrain=training_features(df,validation_end,categories)
    fitted=xgb.train(params,matrix(finaltrain,True),num_boost_round=selected_rounds,verbose_eval=False)
    testdays=sorted(df.loc[(df.date>validation_end)&(df.date<=test_end),'date'].unique())
    test=evaluate(fitted,df,testdays,categories)
    con=connection()
    con.register('test_results',test)
    con.execute(f"COPY test_results TO {literal(output/'test_predictions.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    testmetrics={name:metrics(test.passengers,test[name]) for name in ['baseline','xgboost']}
    breakdown=[]
    for (date,weekend),g in test.groupby(['date','is_weekend']):
        breakdown.append({'date':str(date.date()),'day_type':'weekend' if weekend else 'weekday',
                          **{name:metrics(g.passengers,g[name]) for name in ['baseline','xgboost']}})
    peak=test[test.hour.isin([7,8,9,17,18,19])]
    report={'label_kind':label_kind,'grouping':'weekday_weekend',
        'training_dates':'March 2–14 (first five days supply initial feature history)',
        'validation_dates':'March 15–21','test_dates':'March 22–28',
        'selected_rounds':selected_rounds,'validation':valmetrics,'test':testmetrics,
        'busy_hours':{name:metrics(peak.passengers,peak[name]) for name in ['baseline','xgboost']},
        'daily_test':breakdown,'selected_model_from_validation':champion,
        'selection_policy':'Lower validation MAE; test never selects a model',
        'final_test_model_training_cutoff':'2026-03-21',
        'test_policy':'Frozen model weights; daily features update using preceding complete dates; assumes historical data available without delivery lag',
        'limitations':['March 1 excluded from targets because prior-month duty spillover is absent',
                       'Only route-days with recorded tickets are evaluated; absent route-days remain unknown',
                       'No independent ground truth for actual bus occupancy or missing destinations',
                       'Forecasting assumes prior calendar-day extracts are available; deployment latency unconfirmed']}
    write_json(output/'metrics.json',report)
    fitted.save_model(output/'model.ubj')
    write_json(output/'model_metadata.json',{'features':FEATURES,'categories':categories,'champion':champion,
                                            'training_cutoff':'2026-03-21','label_kind':label_kind})
    print(f'{label_kind}: selected {champion}; test WAPE {testmetrics[champion]["wape"]:.3%}',flush=True)
    return report

def export_profiles(path,model_dir,out,cutoff='2026-03-31'):
    """Weekday/weekend reference profiles, conditioned on one explicit data-through cutoff."""
    model_dir=Path(model_dir)
    metadata=load_json(model_dir/'model_metadata.json')
    df=prepare_frame(path,metadata['label_kind'])
    history=df[df.date<=pd.Timestamp(cutoff)]
    if history.empty: raise ValueError('No history available at cutoff')
    model=xgb.Booster()
    model.load_model(model_dir/'model.ubj')
    categories=metadata['categories']
    series=sorted(history.series_id.unique())
    parts=[]
    for weekend in [0,1]:
        target=pd.DataFrame([(s,h) for s in series for h in range(24)],columns=['series_id','hour'])
        target['date']=pd.Timestamp(cutoff)+pd.Timedelta(days=1)
        target['is_weekend']=weekend
        x=features(history,target,categories)
        pred=model.predict(matrix(x))
        if metadata['champion']=='baseline': pred=x.historical_mean.values
        pred=np.where(x.route_code.isna(),x.historical_mean,pred)
        target['predicted_passengers']=np.maximum(0,pred)
        target['day_type']='weekend' if weekend else 'weekday'
        target['data_through']=cutoff
        target['profile_kind']='reference_profile_at_cutoff_not_specific_date_forecast'
        target=target.drop(columns=['date','is_weekend'])
        parts.append(target)
    result=pd.concat(parts,ignore_index=True)
    con=connection()
    con.register('profiles',result)
    con.execute(f"COPY profiles TO {literal(out)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    return len(result)
