"""Plot a saved report; never rerun or select study seeds."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'experiments/matplotlib-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
fig,axes=plt.subplots(1,3,figsize=(12,3.8),sharey=True)
for ax,track in zip(axes,r['protocol']['tracks']):
    for policy in r['protocol']['policies']:
        rows=[v for v in r['summary'] if v['track']==track and v['policy']==policy]
        ax.plot([v['budget'] for v in rows],[v['normalized_regret'] for v in rows],marker='o',label=policy)
    ax.set(title=track.replace('_',' '),xlabel='Comparisons',xticks=[0,2,4,6],ylim=(0,1));ax.grid(alpha=.2)
axes[0].set_ylabel('Mean normalized regret (lower is better)');axes[-1].legend()
fig.suptitle('Current website algorithm · 12 designed seeds per track · not a user study',fontsize=11);fig.tight_layout()
target=ROOT/'research/results/web-preference-v1.svg';fig.savefig(target);fig.savefig(ROOT/'docs/validation/webcraft/web-study.png',dpi=150);print(target)
