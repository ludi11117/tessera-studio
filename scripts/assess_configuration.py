"""Bounded local architecture measurement, not a model-quality/user study."""
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.decision import analyze
from core import enumerate_feasible, initial_state


def run():
    folder = ROOT/'experiments/runs'/('configuration-'+str(time.time_ns()))
    folder.mkdir(parents=True)
    data = []
    for n in [2, 4, 6]:
        task = {'title': '配置性能开发样本', 'source': 'example', 'category': 'writing', 'brief': '合成文字，只测计算边界', 'facts': {},
                'blocks': [{'id': 'b'+str(k), 'title': '章节'+str(k), 'variants': [
                    {'id': 'v'+str(j), 'template': chr(0x7532+k)*(30+20*j+3*k)} for j in range(3)]} for k in range(n)]}
        state = initial_state(task)
        ranks = [{'combo': c, 'score': sum((k+1)*[0, 2, 1][int(c['b'+str(k)][1:])] for k in range(n))/n}
                 for c in enumerate_feasible(task, state)]
        elapsed = []
        for i in range(16):
            start = time.perf_counter();report = analyze(task, state, ranks, 0)
            ms = (time.perf_counter()-start)*1000
            if i: elapsed.append(ms)
        data.append({'chapters': n, 'task': task, 'state': state, 'space': report['space'],
                     'analysis_ms': elapsed, 'analysis_p50_ms': statistics.median(elapsed),
                     'analysis_p95_ms': sorted(elapsed)[int(.95*(len(elapsed)-1))],
                     'table_bytes_utf8': len(json.dumps(report['space'],ensure_ascii=False).encode())})
    (folder/'inputs.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    sources = ['ai/decision.py', 'static/configuration.js', 'scripts/assess_configuration.py', 'scripts/assess_configuration.cjs']
    manifest = {}
    for name in sources:
        blob=(ROOT/name).read_bytes();target=folder/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(blob)
        manifest[name]=hashlib.sha256(blob).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(folder)


if __name__ == '__main__':run()
