"""Standalone figures and an auditable report for controlled content transfer."""
import argparse
import html
import json
import statistics
from pathlib import Path

from research.model import digest


def build(run,output,replay=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    run,output=Path(run),Path(output)
    if output.exists():raise ValueError('Report directory exists')
    output.mkdir(parents=True)
    rows=[json.loads(s) for s in (run/'metrics.jsonl').read_text(encoding='utf-8').splitlines()]
    config=json.loads((run/'config.json').read_text(encoding='utf-8'))
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    actual_hash=digest([{k:v for k,v in r.items() if k!='fit_ms'} for r in rows])
    if result['semantic_hash']!=actual_hash:raise ValueError('Metric integrity failure')
    replay_hash=json.loads((Path(replay)/'result.json').read_text(encoding='utf-8'))['semantic_hash'] if replay else None
    if replay and replay_hash!=actual_hash:raise ValueError('Replay mismatch')
    summary=[]
    for scenario in config['scenarios']:
        for arm in config['arms']:
            for budget in config['budgets']:
                subset=[r for r in rows if (r['scenario'],r['arm'],r['budget'])==(scenario,arm,budget)]
                entry={'scenario':scenario,'arm':arm,'budget':budget,'n_seeds':len(subset)}
                for split in ('seen','rewrite'):
                    entry[split]={}
                    for metric in ('direction_accuracy','expected_nll','expected_brier','probability_mse','simple_regret_tie_average'):
                        values=[r[split][metric] for r in subset]
                        entry[split][metric]={'mean':statistics.mean(values),'se':statistics.stdev(values)/len(values)**.5 if len(values)>1 else 0,'by_seed':values}
                entry['fit_ms_mean']=statistics.mean(r['fit_ms'] for r in subset)
                summary.append(entry)
    paired=[]
    for scenario in config['scenarios']:
        for budget in config['budgets']:
            neural={r['seed']:r for r in rows if r['scenario']==scenario and r['arm']=='content_neural' and r['budget']==budget}
            for baseline in ('content_linear','content_frozen','interaction'):
                baseline_rows={r['seed']:r for r in rows if r['scenario']==scenario and r['arm']==baseline and r['budget']==budget}
                values=[neural[s]['rewrite']['direction_accuracy']-baseline_rows[s]['rewrite']['direction_accuracy'] for s in sorted(neural)]
                paired.append({'scenario':scenario,'budget':budget,'comparison':f'content_neural - {baseline}',
                               'accuracy_differences':values,'mean':statistics.mean(values),'se':statistics.stdev(values)/len(values)**.5 if len(values)>1 else 0})
    (output/'summary.json').write_text(json.dumps({'run':str(run),'semantic_hash':actual_hash,'replay_hash':replay_hash,'aggregates':summary,'paired_differences':paired},ensure_ascii=False,indent=2),encoding='utf-8')
    colors=['#94a3b8','#475569','#0891b2','#7c3aed','#e76f51']
    for metric,filename,ylabel in [('direction_accuracy','accuracy','Held-out direction accuracy'),('simple_regret_tie_average','regret','Held-out simple regret')]:
        fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
        for ax,scenario in zip(axes.flat,config['scenarios']):
            for arm,color in zip(config['arms'],colors):
                group=[r for r in summary if r['scenario']==scenario and r['arm']==arm]
                x=[r['budget'] for r in group];y=[r['rewrite'][metric]['mean'] for r in group];se=[r['rewrite'][metric]['se'] for r in group]
                ax.plot(x,y,label=arm,color=color,marker='o',markersize=3)
                ax.fill_between(x,[v-s for v,s in zip(y,se)],[v+s for v,s in zip(y,se)],color=color,alpha=.13)
            ax.set_title(scenario);ax.set_xlabel('Explicit pair labels');ax.set_ylabel(ylabel);ax.grid(alpha=.2)
            if metric=='direction_accuracy':ax.set_ylim(.2,1.02);ax.axhline(.5,color='#aaa',linestyle=':',linewidth=.8)
        axes.flat[0].legend(fontsize=8)
        fig.suptitle('Synthetic rewrite transfer | 6 independent seeds | bands: mean +/- 1 SE',fontsize=11)
        fig.savefig(output/f'{filename}.png',dpi=170);fig.savefig(output/f'{filename}.svg');plt.close(fig)
    lines=['# 内容偏好学习：独立评价','',
           '合成配方场景；不是人类偏好数据，也不是大模型微调效果。','',
           f"{len(config['scenarios'])}场景 × {len(config['arms'])}方法 × {len(config['seeds'])}评价种子 × {len(config['budgets'])}预算 = {len(rows)}次拟合。开发种子31、47与评价种子分离。配置、损失、训练步数在评价前固定；未按评价结果调参。",
           '',f"结果语义哈希：`{actual_hash}`；完整重跑：{'一致' if replay_hash==actual_hash else '未核验'}。",'',
           '## 48条明确比较后，新措辞方向准确率','',
           '| 场景 | ID加性 | ID搭配 | 内容线性 | 固定投影搭配 | 可训练投影搭配 |','|---|---:|---:|---:|---:|---:|']
    for scenario in config['scenarios']:
        values=[next(r for r in summary if r['scenario']==scenario and r['arm']==arm and r['budget']==48)['rewrite']['direction_accuracy'] for arm in config['arms']]
        lines.append('| '+scenario+' | '+' | '.join(f"{v['mean']:.1%} ± {v['se']:.1%}" for v in values)+' |')
    lines += ['','数值为跨6个种子的均值 ± 标准误，图带为1个标准误；不宣称显著性。并列预测方向计0.5；推荐遗憾对并列最优取平均，防止候选顺序带来虚假收益。','',
              '![新措辞准确率](accuracy.png)','','![新措辞推荐遗憾](regret.png)','',
              '## 如何解释','',
              '- ID模型能拟合旧候选，但新ID的相关系数仍为零；这里0.5是设计预期，不能外推为ID基线在原候选上无效。summary.json同时保留原候选结果。',
              '- 内容模型具有受控风格改写迁移能力。词汇哈希与文字统计不等于语义理解，主题词变化与替换措辞也不能代表开放领域泛化。',
              '- 可训练小网络确实执行反向传播和Adam训练，但不保证优于内容线性或固定投影。保持可选，未自动替换用户基线。',
              '- opaque_codes_failure隐藏规则与新代号之间没有可学习桥梁；随机波动不能解释为识别了隐藏含义。',
              '- 48次比较已具有明显反馈负担；4/12/24条学习曲线和逐种子数据用于审查低预算收益。尚无真实用户时间成本结论。',
              '- 不使用训练集准确率证明泛化。留出候选的文字和标签从未进入fit；所有方法共享同一训练标签序列。未来候选只用于枚举评分，历史候选以不可变归档读取。',
              '- 神经投影后只对线性头计算曲率；忽略表示不确定性，不能称校准贝叶斯后验。本轮不声称实现BoTorch PairwiseGP或qEUBO。','',
              '## 可核验文件','',
              f'- 原始运行：`{run}`；含 config/environment、逐次metrics、可回放traces、源码快照与12个内容模型checkpoint。',
              '- summary.json含各预算、场景、方法的NLL、Brier、概率误差、推荐遗憾、拟合时间、逐种子值和配对差异。',
              '- checkpoint使用NumPy非pickle数组、SHA-256完整性检查与任务上下文/编码器校验；在新改写上预测，不复制标签。','',
              '## 技术边界与后续验收','',
              '当前达到完整AI应用加可复现偏好研究原型的水平。还不能宣称开放域专属大模型、高水平算法创新或已证明真实需求收益。后续用真实任务试用验证成品成功率/修改成本，再引入预训练语义编码、GP/qEUBO强对照及更多独立任务。','']
    md='\n'.join(lines);(output/'report.md').write_text(md,encoding='utf-8')
    table=''.join('<tr><th>'+html.escape(line.split('|')[1].strip())+'</th>'+''.join('<td>'+html.escape(c.strip())+'</td>' for c in line.split('|')[2:-1])+'</tr>' for line in lines if line.startswith('| ') )
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>内容偏好学习 · 受控评价</title><link rel="stylesheet" href="report.css"><main><a href="/">返回AI工作室</a><h1>内容偏好学习：改写后的推荐</h1><p>4场景 × 5方法 × 6种子 × 5预算，600次独立拟合。合成数据，不代表真实用户收益。</p><h2>48条明确比较后的留出准确率</h2><div class="table"><table>{table}</table></div><p>均值 ± 标准误；新文字全部使用新ID。ID模型对旧文字的预测另见原始指标。</p><img src="accuracy.png" alt="各预算下留出准确率"><img src="regret.png" alt="各预算下留出推荐遗憾"><h2>结论边界</h2><p>内容模型能迁移部分风格偏好；可训练网络没有普遍胜过简单基线。文字统计与词片段哈希不能代替语义理解。缺少语言线索时仍会失败。</p><p>只训练本任务的小型偏好模型，不微调硅基流动大模型。神经投影的不确定性尚未纳入估计。GP/qEUBO与真实任务对照尚未完成。</p><details><summary>运行审计与局限全文</summary><pre>{html.escape(md)}</pre></details><p>语义哈希：<code>{actual_hash}</code>；独立重跑：{'一致' if replay_hash==actual_hash else '未核验'}。</p></main></html>'''
    (output/'report.html').write_text(page,encoding='utf-8')
    (output/'report.css').write_text('body{margin:0;background:#f5f6fa;color:#233047;font:16px/1.7 system-ui}main{max-width:1100px;padding:36px;margin:auto}img{width:100%;background:white;margin:16px 0}table{border-collapse:collapse;background:white;font-size:14px}td,th{padding:10px;border:1px solid #dce0e8;text-align:left}.table{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}h1,h2{line-height:1.3}',encoding='utf-8')
    print(json.dumps({'rows':len(rows),'semantic_hash':actual_hash,'report':str(output/'report.html')},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--replay',type=Path)
    args=p.parse_args();build(args.run,args.output,args.replay)
