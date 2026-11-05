import argparse
from pathlib import Path
from .storage import write_json

def main():
    parser=argparse.ArgumentParser(description='Madrasflow: audited ETM forecasting and service scenarios')
    sub=parser.add_subparsers(dest='command',required=True)
    ingest=sub.add_parser('ingest',help='Validate daily CSVs and build compact hourly data')
    ingest.add_argument('--source',required=True)
    ingest.add_argument('--data',default='data')
    ingest.add_argument('--limit',type=int)
    seg=sub.add_parser('segments',help='Build training-only stage-interval estimates for pilot routes')
    seg.add_argument('--data',default='data')
    seg.add_argument('--output',default='artifacts/segments')
    seg.add_argument('--routes',type=int,default=10)
    seg.add_argument('--train-end',default='2026-03-14')
    train=sub.add_parser('train',help='Chronological benchmark vs one XGBoost model')
    train.add_argument('--input',default='data/hourly.parquet')
    train.add_argument('--output',default='artifacts/boardings')
    train.add_argument('--kind',choices=['boardings','segments'],default='boardings')
    train.add_argument('--rounds',type=int,default=100)
    profiles=sub.add_parser('profiles',help='Export 24-hour weekday/weekend reference profiles')
    profiles.add_argument('--input',default='data/hourly.parquet')
    profiles.add_argument('--model-dir',default='artifacts/boardings')
    profiles.add_argument('--output',default='artifacts/weekday_weekend_profiles.parquet')
    profiles.add_argument('--cutoff',default='2026-03-31')
    refit=sub.add_parser('refit',help='Train a separate candidate through a new completed cutoff; does not promote it')
    refit.add_argument('--input',default='data/hourly.parquet')
    refit.add_argument('--approved-model-dir',default='artifacts/boardings')
    refit.add_argument('--output',required=True)
    refit.add_argument('--cutoff',required=True)
    plan=sub.add_parser('plan',help='Conditional minimum service; flows must describe section crossings')
    plan.add_argument('--flows',type=float,nargs='+',required=True)
    plan.add_argument('--trips',type=int,required=True)
    plan.add_argument('--target-load',type=float,default=40)
    plan.add_argument('--cycle-minutes',type=float)
    plan.add_argument('--output',default='artifacts/scenario.json')
    transfer=sub.add_parser('reallocate',help='Check a conditional spare-trip transfer and protect donor service')
    transfer.add_argument('--donor-flows',type=float,nargs='+',required=True)
    transfer.add_argument('--donor-trips',type=int,required=True)
    transfer.add_argument('--receiver-flows',type=float,nargs='+',required=True)
    transfer.add_argument('--receiver-trips',type=int,required=True)
    transfer.add_argument('--transfer',type=int,default=1)
    transfer.add_argument('--target-load',type=float,default=40)
    transfer.add_argument('--output',default='artifacts/reallocation.json')
    server=sub.add_parser('serve',help='Run the connected dashboard and local operations API')
    server.add_argument('--host',default='127.0.0.1')
    server.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if args.command=='serve':
        from .dashboard import serve
        return serve(args.host,args.port)
    if args.command=='ingest':
        from .ingest import ingest,hourly_table
        ingest(args.source,args.data,args.limit)
        hourly_table(args.data,Path(args.data)/'hourly.parquet')
    elif args.command=='segments':
        from .segments import build_segments
        build_segments(args.data,args.output,args.train_end,args.routes)
    elif args.command=='train':
        from .forecast import train_and_evaluate
        train_and_evaluate(args.input,args.output,args.kind,args.rounds)
    elif args.command=='profiles':
        from .forecast import export_profiles
        print('Exported profile rows:',export_profiles(args.input,args.model_dir,args.output,args.cutoff))
    elif args.command=='refit':
        from .forecast import refit_candidate
        print('Saved candidate:',refit_candidate(args.input,args.approved_model_dir,args.output,args.cutoff))
    elif args.command=='plan':
        from .planning import scenario
        result=scenario(args.flows,args.trips,args.target_load,args.cycle_minutes)
        write_json(args.output,result)
        print(result)
    elif args.command=='reallocate':
        from .planning import reallocate
        result=reallocate(args.donor_flows,args.donor_trips,args.receiver_flows,args.receiver_trips,
                          args.transfer,args.target_load)
        write_json(args.output,result)
        print(result)

if __name__=='__main__': main()
