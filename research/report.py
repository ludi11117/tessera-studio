"""Standalone publication-style plots and a local HTML/Markdown report."""
import argparse
import html
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "D:/CodexWork/cache/intent-workbench-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COLORS = ["#7c827d", "#d3904b", "#497ea0", "#a17db5", "#26784d", "#b65055", "#a4ae63"]


def interval(values):
    a = np.array(values, dtype=float)
    if not len(a):
        return None, None, None
    rng = np.random.default_rng(42)
    sampled = a[rng.integers(0, len(a), (2000, len(a)))].mean(axis=1)
    return float(a.mean()), float(np.quantile(sampled,.025)), float(np.quantile(sampled,.975))


def generate(run, publish=False):
    rows = json.loads((run/"metrics.json").read_text(encoding="utf-8"))
    config = json.loads((run/"config.json").read_text(encoding="utf-8"))
    manifest = json.loads((run/"manifest.json").read_text(encoding="utf-8"))
    counter = json.loads((run/"counterexample.json").read_text(encoding="utf-8"))
    arms = [a["id"] for a in config["arms"]]
    scenarios = [s["id"] for s in config["scenarios"] if s["id"]!="infeasible"]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["scenario"],r["arm"],r["budget"])].append(r)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False,"svg.fonttype":"none"})
    for mode in ("regret","cost"):
        fig,axes=plt.subplots(2,3,figsize=(15,8.8),layout="constrained")
        for ax,scenario in zip(axes.flat,scenarios):
            for j,arm in enumerate(arms):
                points=[groups[(scenario,arm,b)] for b in config["budgets"]]
                means=[interval([r["regret"] for r in p if r["regret"] is not None]) for p in points]
                x=config["budgets"] if mode=="regret" else [np.mean([r["user_cost_proxy_observed"] for r in p]) for p in points]
                y=[m[0] for m in means]
                ax.plot(x,y,label=arm,color=COLORS[j],linewidth=1.6,linestyle="--" if "current" in arm else "-",marker="o",markersize=3)
                ax.fill_between(x,[m[1] for m in means],[m[2] for m in means],color=COLORS[j],alpha=.10)
            ax.set_title(scenario.replace("_"," "),loc="left",fontweight="bold")
            ax.set_xlabel("Feedback budget" if mode=="regret" else "Observed synthetic cost units")
            ax.set_ylabel("True-oracle simple regret (lower is better)")
            ax.grid(alpha=.17)
        fig.suptitle("SIMULATION ONLY · finite candidate preference benchmark\nMean and 95% seed-level bootstrap intervals; intervals are descriptive",fontsize=13)
        handles,labels=axes[0,0].get_legend_handles_labels()
        fig.legend(handles,labels,loc="outside lower center",ncol=4,frameon=False,fontsize=8)
        fig.savefig(run/f"{mode}.png",dpi=160)
        fig.savefig(run/f"{mode}.svg")
        plt.close(fig)
    final=[r for r in rows if r["budget"]==max(config["budgets"]) and r["actual_feedback"]]
    fig,ax=plt.subplots(figsize=(12,4.8),layout="constrained")
    planning=[np.mean([1000*r["planning_seconds"]/r["actual_feedback"] for r in final if r["arm"]==arm]) for arm in arms]
    fitting=[np.mean([1000*r["fitting_seconds"]/r["actual_feedback"] for r in final if r["arm"]==arm]) for arm in arms]
    x=np.arange(len(arms));ax.bar(x-.2,planning,.4,label="Query pool + planning",color="#3b7d59");ax.bar(x+.2,fitting,.4,label="Model fitting",color="#a5b994")
    ax.set_xticks(x,arms,rotation=18,ha="right");ax.set_ylabel("Mean milliseconds per answered query");ax.set_title("Measured CPU time · excludes human reading and candidate preparation",loc="left");ax.legend(frameon=False)
    fig.savefig(run/"planning.png",dpi=160);fig.savefig(run/"planning.svg");plt.close(fig)
    summary=[]
    for scenario in [s["id"] for s in config["scenarios"]]:
        for arm in arms:
            p=groups[(scenario,arm,max(config["budgets"]))]
            mean,lo,hi=interval([r["regret"] for r in p if r["regret"] is not None])
            summary.append({"scenario":scenario,"arm":arm,"regret":mean,"regret_ci95":[lo,hi],
                            "feedback":float(np.mean([r["actual_feedback"] for r in p])),
                            "cost":float(np.mean([r["user_cost_proxy_observed"] for r in p])),
                            "nll":float(np.mean([r["heldout_nll"] for r in p if r["heldout_nll"] is not None])) if any(r["heldout_nll"] is not None for r in p) else None,
                            "brier":float(np.mean([r["heldout_brier"] for r in p if r["heldout_brier"] is not None])) if any(r["heldout_brier"] is not None for r in p) else None,
                            "constraint_violations":sum(r["constraint_violations"] for r in p)})
    (run/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    paired=[]
    for scenario in scenarios:
        baseline={r["seed"]:r for r in groups[(scenario,"interaction_uncertainty",max(config["budgets"]))]}
        for arm in ("additive_uncertainty","interaction_random","interaction_kg","interaction_cost_kg"):
            delta=[r["regret"]-baseline[r["seed"]]["regret"] for r in groups[(scenario,arm,max(config["budgets"]))]]
            m,l,h=interval(delta);paired.append({"scenario":scenario,"arm":arm,"versus":"interaction_uncertainty","mean_regret_difference":m,"ci95":[l,h]})
    (run/"paired_differences.json").write_text(json.dumps(paired,indent=2),encoding="utf-8")
    def num(v):return "—" if v is None else f"{v:.3f}"
    lines=["# 可复现实验报告（仅模拟）","",f"独立评价任务种子：{len(manifest['independent_seeds'])}；真实参与者：0；最大反馈预算：{max(config['budgets'])}。",f"语义结果哈希：`{manifest['semantic_hash']}`。", "", "旧V1行保留平均损失，且只问当前背景；它是现状参照。固定先验加性/交互模型均使用总和损失与相同λ；随机、不确定性、KG与成本KG使用相同合法查询池生成器与预算。current行是背景覆盖消融，不用于单独归因策略提升。", "", "KG为Laplace曲率附近的一次秩一Newton假想更新，不是qEUBO实现，不继承其理论保证。成本为人工构造单位，不是实测认知时间。误设成本场景故意让实际成本与代理不一致。", "", "正式/轻松反例："]
    for r in counter["rows"]:
        lines.append(f"- {r['coverage']} / {r['model']}: {r['reversal_correct']}/{r['probe_count']} 个背景方向正确，{r['pair_count']} 条覆盖反馈。")
    lines += ["", "| 场景 | 方法 | 遗憾 | 95%区间 | 实际反馈 | 模拟成本 | 留出NLL | 留出Brier | 约束违规 |", "|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in summary:
        lines.append(f"|{r['scenario']}|{r['arm']}|{num(r['regret'])}|[{num(r['regret_ci95'][0])}, {num(r['regret_ci95'][1])}]|{r['feedback']:.1f}|{r['cost']:.2f}|{num(r['nll'])}|{num(r['brier'])}|{r['constraint_violations']}|")
    lines += ["", "失败与限制：", "", "- 不保证每个场景均改善。请看各场景逐种子结果和配对差异，不能只挑最有利的一行。", "- 置信区间按独立模拟任务种子重采样；不是按点击重采样，也不是人类总体置信区间。小样本区间是描述性统计，未做多重检验校正。", "- 留出查询从训练池排除。NLL/Brier相对已知模拟响应分布计算；不代表语言语义或跨用户泛化。", "- 无解时不定义简单遗憾，记录停止原因；不能记作遗憾为0。",f"- 规划超时回退次数：{manifest['fallback_count']}。时间会随硬件负载变化，不纳入语义重现哈希。", "- 未实现Pairwise GP/qEUBO强基线、内容编码或真实用户试点；目前不能宣称方法新颖性或真实效率收益。"]
    (run/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    htmlrows="".join(f"<tr><td>{html.escape(r['scenario'])}</td><td>{html.escape(r['arm'])}</td><td>{num(r['regret'])}</td><td>[{num(r['regret_ci95'][0])}, {num(r['regret_ci95'][1])}]</td><td>{r['feedback']:.1f}</td><td>{r['cost']:.2f}</td><td>{num(r['nll'])}</td><td>{num(r['brier'])}</td><td>{r['constraint_violations']}</td></tr>" for r in summary)
    content=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>组合偏好实验 · 意图</title><link rel="stylesheet" href="report.css"></head><body><main><a href="/">← 回到工作台</a><p class="tag">REPRODUCIBLE RESEARCH / SIMULATION ONLY</p><h1>组合偏好与主动比较：第一轮实验</h1><p>7种场景 · 7种方法 · {len(manifest['independent_seeds'])}个独立评价种子 · 最多{max(config['budgets'])}次反馈。真实参与者为0。</p><aside>这些曲线只验证有限候选上的算法行为。尚未证明真实写作效率、产物质量或方法原创性。</aside><h2>同一反馈预算，最后推荐有多接近模拟最优？</h2><p>阴影是按独立任务种子计算的描述性95%自助法区间。虚线为当前背景限制的对照，与其他方法的查询覆盖不同。</p><img src="regret.png" alt="不同模拟场景的遗憾与反馈预算曲线"><h2>把阅读与背景切换代理成本计入</h2><p>成本单位是合成代理；误设场景中实际合成成本与策略代理相反。不代表人类阅读秒数。</p><img src="cost.png" alt="遗憾与合成反馈成本曲线"><h2>计算开销也要报告</h2><img src="planning.png" alt="CPU查询规划和模型拟合耗时"><h2>完整结果表</h2><div class="table-scroll"><table><thead><tr><th>场景</th><th>方法</th><th>遗憾↓</th><th>95%区间</th><th>实际反馈</th><th>成本</th><th>NLL↓</th><th>Brier↓</th><th>违规</th></tr></thead><tbody>{htmlrows}</tbody></table></div><h2>方法与边界</h2><p>加性与交互模型使用相同总和损失、固定L2先验和候选池。交互特征连接相邻段落及首尾。原始V1单独保留平均损失，不能把所有差异归因于交互项。</p><p>KG采用MAP与Laplace曲率附近的一步秩一Newton假想更新；它是近似策略，不是qEUBO复现，未继承原论文保证。未实现语言内容泛化、GP强基线或真实用户实验。</p><p>完整配置、原始查询日志、逐种子指标、配对差异和源码快照见项目 experiments/runs/{html.escape(run.name)}。</p><code>{manifest['semantic_hash']}</code></main></body></html>'''
    (run/"report.html").write_text(content,encoding="utf-8")
    (run/"report.css").write_text('body{margin:0;background:#f4f6ef;color:#2b4631;font:15px/1.85 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1250px;margin:40px auto;padding:0 30px 70px}a{color:#4b7a41}.tag{letter-spacing:2px;color:#7e8f70;font-size:12px;margin-top:35px}h1{font-size:34px;margin-bottom:14px}h2{margin-top:48px;font-size:22px}p{max-width:1000px;color:#6a7a60}aside{border-left:4px solid #b7a766;background:#f0ecdc;padding:15px 20px;margin:24px 0}img{width:100%;background:#fff;border-radius:10px;border:1px solid #dce6d3}.table-scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap;font-size:12px;width:100%}td,th{padding:9px 12px;border-bottom:1px solid #dae3d1;text-align:left}th{background:#e7eddf}code{font-size:11px;overflow-wrap:anywhere}',encoding="utf-8")
    if publish:
        latest=ROOT/"experiments/latest";latest.mkdir(parents=True,exist_ok=True)
        for name in ("report.html","report.css","regret.png","cost.png","planning.png"):
            shutil.copy2(run/name,latest/name)
        (latest/"source-run.json").write_text(json.dumps({"run":str(run),"semantic_hash":manifest["semantic_hash"]},indent=2),encoding="utf-8")
    print(json.dumps({"report":str(run/"REPORT.md"),"published_local":publish}))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("run",type=Path);parser.add_argument("--publish",action="store_true");args=parser.parse_args();generate(args.run,args.publish)
