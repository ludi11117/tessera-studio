"""Standalone publication-sized plots of the saved retraining study report."""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
cache=ROOT/'experiments'/'matplotlib-cache';cache.mkdir(parents=True,exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR',str(cache))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('report',type=Path);args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report=json.loads(args.report.read_text(encoding='utf-8'))
    fig,axes=plt.subplots(2,2,figsize=(10,7),sharex=True,sharey=True,layout='constrained')
    colors={'random':'#5470C6','entropy':'#D18631','decision_value':'#258777'}
    for row,model in enumerate(['semantic_deep','semantic_linear']):
        for col,domain in enumerate(['same_wording','new_wording']):
            ax=axes[row,col]
            for policy in report['policies']:
                records=sorted([r for r in report['summary'] if r['model']==model and r['domain']==domain and r['policy']==policy],key=lambda r:r['total_feedback'])
                x=[r['total_feedback'] for r in records];y=[r['mean'] for r in records]
                lo=[r['seed_cluster_bootstrap_95_percentile'][0] for r in records];hi=[r['seed_cluster_bootstrap_95_percentile'][1] for r in records]
                ax.plot(x,y,marker='o',label=policy.replace('_',' '),color=colors[policy],linewidth=1.8,markersize=4)
                ax.fill_between(x,lo,hi,color=colors[policy],alpha=.10,linewidth=0)
            ax.set_title(('Deep ensemble' if row==0 else 'Matched-feedback linear')+' / '+domain.replace('_',' '),fontsize=11)
            ax.set_xticks([4,6,8,10]);ax.set_ylim(0,1);ax.grid(axis='y',alpha=.18)
            ax.spines[['top','right']].set_visible(False)
            if col==0:ax.set_ylabel('Normalized oracle regret (lower is better)')
            if row==1:ax.set_xlabel('Total feedback = 4 shared + additional comparisons')
    axes[0,0].legend(frameon=False,fontsize=9)
    fig.suptitle('Actual retraining with synthetic feedback\n'+str(len(report['profiles']))+' fixed profiles x '+str(len(report['seeds']))+' paired seeds; shaded: seed-cluster bootstrap 95% interval',fontsize=12)
    fig.savefig(args.report.parent/'retraining-curves.svg')
    fig.savefig(args.report.parent/'retraining-curves.png',dpi=180)
    plt.close(fig)
    print(args.report.parent/'retraining-curves.svg')


if __name__=='__main__':main()
