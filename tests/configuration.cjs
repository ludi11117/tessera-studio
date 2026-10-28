'use strict';
const assert=require('node:assert/strict'),C=require('../static/configuration.js');
let state=19827;
function random(){state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296;}
// Independent list-scan oracle: does not use masks or the production query.
function oracle(rows,q,omit){return rows.filter(c=>c.body_characters>=q.min&&c.body_characters<=q.max&&c.change_count<=q.budget&&Object.entries(q.anchors).every(([k,v])=>k===omit||c.combo[k]===v));}
const cases=[];
for(const n of [2,4,6]){
  const blocks=Array.from({length:n},(_,k)=>({id:'b'+k,variants:[0,1,2].map(v=>({id:String(v)}))}));
  const rows=[];
  for(let i=0;i<3**n;i++){
    let j=i;const combo={};for(const b of blocks){combo[b.id]=String(j%3);j=Math.floor(j/3);}
    // Synthetic hard filter (stand-in for the already-checked server table).
    if(i%7===2)continue;
    rows.push({id:String(i),combo,score:Math.floor(random()*8),body_characters:20+Math.floor(random()*300),change_count:Object.values(combo).filter(v=>v!=='0').length});
  }
  const ix=C.index(rows,blocks);
  for(let trial=0;trial<200;trial++){
    const anchors={};for(const b of blocks)if(random()<.6)anchors[b.id]=String(Math.floor(random()*3));
    const q={anchors,min:Math.floor(random()*100),max:150+Math.floor(random()*180),budget:Math.floor(random()*(n+1))};
    const r=C.query(ix,q),expected=oracle(rows,q);
    assert.deepEqual(new Set(r.rows.map(c=>c.id)),new Set(expected.map(c=>c.id)));
    if(expected.length){assert.equal(r.best.score,Math.max(...expected.map(c=>c.score)));assert.equal(r.best.change_count,Math.min(...expected.filter(c=>c.score===r.best.score).map(c=>c.change_count)));}
    for(const b of blocks)for(const v of b.variants){
      const count=oracle(rows,q,b.id).filter(c=>c.combo[b.id]===v.id).length;
      assert.equal(r.support[b.id][v.id],count);
    }
    const front=expected.filter(c=>!expected.some(p=>p.score>=c.score&&p.change_count<=c.change_count&&(p.score>c.score||p.change_count<c.change_count)));
    assert.deepEqual(new Set(r.frontier),new Set(front.map(c=>c.id)));
    if(!expected.length&&r.window_count){
      const forKeys=keys=>oracle(rows,{...q,anchors:Object.fromEntries(keys.map(k=>[k,q.anchors[k]]))});
      assert.equal(forKeys(r.core).length,0);
      for(const k of r.core)assert(forKeys(r.core.filter(x=>x!==k)).length>0);
      // Enumerate the entire relaxation power set independently, then test minimality.
      const keys=Object.keys(anchors),valid=[];
      for(let bits=0;bits<2**keys.length;bits++){
        const relax=keys.filter((_,i)=>bits&(1<<i));
        if(forKeys(keys.filter(k=>!relax.includes(k))).length)valid.push(relax);
      }
      const minimal=valid.filter(s=>!valid.some(t=>t.length<s.length&&t.every(k=>s.includes(k))));
      assert.equal(r.repair_count,minimal.length);
      for(const s of r.repairs){assert(minimal.some(t=>t.length===s.relax.length&&t.every(k=>s.relax.includes(k))));assert(forKeys(keys.filter(k=>!s.relax.includes(k))).some(c=>c.id===s.witness.id));}
    }
  }
  cases.push({chapters:n,candidates:rows.length,queries:200});
}
assert.deepEqual(C.query(C.index([],[])).rows,[]);
assert.throws(()=>C.query(C.index([],[]),{anchors:{missing:'x'}}));
assert.throws(()=>C.query(C.index([],[]),{min:10,max:2}));
console.log(JSON.stringify({result:'PASS',cases,checks:['600 independent scan queries','all conditional counts','optimal score and least changes','complete frontier','irreducible conflict core','exhaustive minimal repairs','empty and invalid input']}));
