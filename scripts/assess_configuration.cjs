'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{performance}=require('node:perf_hooks'),C=require('../static/configuration.js');
const folder=process.argv[2];if(!folder)throw new Error('Pass the D-drive experiment folder');
const inputs=JSON.parse(fs.readFileSync(path.join(folder,'inputs.json'),'utf8')),results=[],trace=[];
const percentile=(a,p)=>a.slice().sort((a,b)=>a-b)[Math.floor(p*(a.length-1))];
for(const data of inputs){
  const rows=data.space.candidates,blocks=data.task.blocks,start=performance.now(),ix=C.index(rows,blocks),indexMs=performance.now()-start,timings=[],scanTimes=[];
  for(let i=0;i<130;i++){
    const anchors={};if(i%4)anchors['b'+(i%blocks.length)]='v'+String(i%3);
    if(i%5===0)anchors['b'+((i+1)%blocks.length)]='v'+String((i+2)%3);
    const q={anchors,min:i%3*30,max:i%7===0?i%3*30+10:10000,budget:i%2?blocks.length:Math.floor(i/2)%(blocks.length+1)};
    let t=performance.now();const r=C.query(ix,q);const indexed=performance.now()-t;
    // Independent direct scan with the same conditional counts and objectives.
    t=performance.now();const window=rows.filter(c=>c.body_characters>=q.min&&c.body_characters<=q.max&&c.change_count<=q.budget);
    const matches=(c,omit)=>Object.entries(anchors).every(([k,v])=>k===omit||c.combo[k]===v);
    const pool=window.filter(c=>matches(c)),support={};
    for(const b of blocks){support[b.id]={};for(const v of b.variants)support[b.id][v.id]=window.filter(c=>matches(c,b.id)&&c.combo[b.id]===v.id).length;}
    const front=pool.filter(c=>!pool.some(p=>p.score>=c.score&&p.change_count<=c.change_count&&(p.score>c.score||p.change_count<c.change_count))).map(c=>c.id);
    const scan=performance.now()-t;
    assert.deepEqual(new Set(r.rows.map(c=>c.id)),new Set(pool.map(c=>c.id)));assert.deepEqual(r.support,support);assert.deepEqual(new Set(r.frontier),new Set(front));
    // Timing comparison excludes no-solution repairs, which the scan oracle does not compute.
    if(i>=10&&pool.length){timings.push(indexed);scanTimes.push(scan);}
    trace.push({chapters:blocks.length,query:q,eligible:r.rows.length,best:r.best?.id||null,frontier:r.frontier,core:r.core,repairs:r.repairs.map(s=>({relax:s.relax,witness:s.witness.id})),indexed_ms:indexed,scan_ms:scan});
  }
  // Adversarial full table with all tied scores, preserving all frontier equivalents.
  const tied=C.index(rows.map(c=>({...c,score:0,change_count:1})),blocks),adversarial=[];
  for(let i=0;i<30;i++){const t=performance.now();C.query(tied);if(i>=5)adversarial.push(performance.now()-t);}
  results.push({chapters:blocks.length,candidates:rows.length,table_bytes_utf8:data.table_bytes_utf8,python_analysis_p50_ms:data.analysis_p50_ms,python_analysis_p95_ms:data.analysis_p95_ms,index_ms:indexMs,
    query_p50_ms:percentile(timings,.5),query_p95_ms:percentile(timings,.95),scan_p50_ms:percentile(scanTimes,.5),scan_p95_ms:percentile(scanTimes,.95),all_tied_p95_ms:percentile(adversarial,.95),measured_feasible_queries:timings.length});
}
const report={result:'PASS',paid_calls:0,synthetic:true,node:process.version,results,
  limits:['Local microbenchmark; no user-time, content quality or model outcome claims.','Python timings exclude model fitting/inference, HTTP and serialization.','Index timing includes no text generation. Scan timing omits minimal repairs; no-solution queries excluded from timing comparison.','Small candidate bound (3^6); no claim of scaling to arbitrary configuration spaces.']};
fs.writeFileSync(path.join(folder,'trace.json'),JSON.stringify(trace,null,2));fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({folder,...report},null,2));
