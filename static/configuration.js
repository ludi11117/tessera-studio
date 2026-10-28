'use strict';
// Exact, task-local interactive configuration over the server's feasible table.
// No text generation, persistence, implicit feedback, or relaxed hard conditions.
const Configuration = (() => {
  function index(candidates, blocks) {
    const masks = new Map();
    for (const b of blocks) for (const v of b.variants) masks.set(b.id+'\0'+v.id, 0n);
    candidates.forEach((c,i) => {
      const bit=1n<<BigInt(i);
      for (const b of blocks) {
        const k=b.id+'\0'+c.combo[b.id];
        if (!masks.has(k)) throw new Error('候选表与章节版本不一致，请重新载入');
        masks.set(k,masks.get(k)|bit);
      }
    });
    return {candidates,blocks,masks,all:(1n<<BigInt(candidates.length))-1n};
  }
  function count(bits) {let n=0;while(bits){bits&=bits-1n;n++;}return n;}
  function query(ix, {anchors={},min=0,max=Infinity,budget=6}={}) {
    const keys=Object.keys(anchors);
    if (!(Number.isFinite(min)&&min>=0&&(max===Infinity||Number.isFinite(max))&&max>=min&&Number.isInteger(budget)&&budget>=0)) throw new Error('篇幅区间或改动上限无效');
    for(const k of keys) if(!ix.masks.has(k+'\0'+anchors[k])) throw new Error('保留的章节版本已变化，请重置画布');
    let window=0n;
    ix.candidates.forEach((c,i)=>{if(c.body_characters>=min&&c.body_characters<=max&&c.change_count<=budget)window|=1n<<BigInt(i);});
    const intersect=ks=>ks.reduce((bits,k)=>bits&ix.masks.get(k+'\0'+anchors[k]),window);
    const bits=intersect(keys),rows=ix.candidates.filter((_,i)=>(bits&(1n<<BigInt(i)))!==0n);
    const sorted=rows.slice().sort((a,b)=>b.score-a.score||a.change_count-b.change_count||a.id.localeCompare(b.id));
    const support={};
    for(const b of ix.blocks){const other=intersect(keys.filter(k=>k!==b.id));support[b.id]={};
      for(const v of b.variants) support[b.id][v.id]=count(other&ix.masks.get(b.id+'\0'+v.id));
    }
    let core=[],repairs=[];
    if(!rows.length&&window){
      core=keys.slice();
      for(const k of keys) {const reduced=core.filter(x=>x!==k);if(!intersect(reduced))core=reduced;}
      const sets=new Map();
      ix.candidates.forEach((c,i)=>{if(!(window&(1n<<BigInt(i))))return;
        const relax=keys.filter(k=>c.combo[k]!==anchors[k]);
        const signature=JSON.stringify(relax.slice().sort());
        const prior=sets.get(signature);
        if(!prior||c.score>prior.witness.score||(c.score===prior.witness.score&&c.change_count<prior.witness.change_count))sets.set(signature,{relax,witness:c});
      });
      for(const s of [...sets.values()].sort((a,b)=>a.relax.length-b.relax.length||a.witness.id.localeCompare(b.witness.id))) {
        if(!repairs.some(r=>r.relax.every(k=>s.relax.includes(k))))repairs.push(s);
      }
    }
    // Scores are fixed within the snapshot; this is not a prediction of retraining.
    const frontier=sorted.filter(c=>!sorted.some(p=>p.change_count<=c.change_count&&p.score>=c.score&&(p.change_count<c.change_count||p.score>c.score))).map(c=>c.id);
    return {rows:sorted,support,best:sorted[0]||null,frontier,core,repairs:repairs.slice(0,6),repair_count:repairs.length,window_count:count(window),total:ix.candidates.length};
  }
  return {index,query};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=Configuration;
