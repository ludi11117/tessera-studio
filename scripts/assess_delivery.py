"""Create a pending crossover study or score manually collected evidence logs."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research.delivery_benchmark import load_tasks,build_plan,empty_records,assess


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    new=sub.add_parser('plan');new.add_argument('--model');new.add_argument('--participants',type=int,default=10);new.add_argument('--seed',type=int,default=101)
    score=sub.add_parser('score');score.add_argument('--plan',type=Path,required=True);score.add_argument('--log',type=Path,required=True);score.add_argument('--evidence-root',type=Path)
    args=parser.parse_args();out=ROOT/'experiments'/'runs'/('delivery-'+args.command+'-'+str(time.time_ns()));out.mkdir(parents=True)
    if args.command=='plan':
        tasks=load_tasks(ROOT/'research/fixtures/delivery_tasks.json');plan=build_plan(tasks,args.model,args.participants,args.seed);log=empty_records(plan)
        write(out/'protocol.json',plan);write(out/'records.pending.json',log);result=assess(plan,log)
        write(out/'score.json',result)
    else:
        plan=json.loads(args.plan.read_text(encoding='utf-8'));log=json.loads(args.log.read_text(encoding='utf-8'));result=assess(plan,log,args.evidence_root)
        write(out/'score.json',result);write(out/'source-inputs.json',{'plan':str(args.plan.resolve()),'log':str(args.log.resolve()),'evidence_root':str(args.evidence_root.resolve()) if args.evidence_root else None})
    print(json.dumps({'folder':str(out),'status':result['status'],'complete_pairs':result['complete_pairs'],'paired_means':result['paired_arm_means']},ensure_ascii=False))


if __name__=='__main__':main()
