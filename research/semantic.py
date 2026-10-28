"""Offline frozen Transformer inference; training never changes these weights."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import numpy as np
from core import Invalid
from research.model import digest

HOME=Path(os.environ.get('INTENT_EMBEDDING_HOME','D:/CodexWork/cache/intent-semantic-minilm'))
VERSION='multilingual-minilm-onnx-windowed-mean-v1'
_instance=None
_instance_lock=threading.Lock()


def availability():
    files=all((HOME/name).is_file() for name in ('source.json','tokenizer.json','onnx/model_quint8_avx2.onnx'))
    packages=all(importlib.util.find_spec(name) is not None for name in ('onnxruntime','tokenizers'))
    return {'available':files and packages,'files_ready':files,'packages_ready':packages,'local_directory':str(HOME),'paid_calls':0}


class SemanticEncoder:
    dimension=384

    def __init__(self,folder=HOME):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.folder=Path(folder);self.lock=threading.RLock();self.memory={}
        source=json.loads((self.folder/'source.json').read_text('utf-8'))
        for name in ('tokenizer.json','onnx/model_quint8_avx2.onnx','1_Pooling/config.json','sentence_bert_config.json'):
            if hashlib.sha256((self.folder/name).read_bytes()).hexdigest()!=source['files'][name]['sha256']:raise Invalid('本地语义模型文件校验失败')
        config=json.loads((self.folder/'sentence_bert_config.json').read_text('utf-8'))
        pool=json.loads((self.folder/'1_Pooling/config.json').read_text('utf-8'))
        if not pool.get('pooling_mode_mean_tokens') or pool.get('word_embedding_dimension')!=384:raise Invalid('语义模型池化配置不匹配')
        self.max_tokens=min(256,config.get('max_seq_length',128));self.max_chunks=64
        self.tokenizer=Tokenizer.from_file(str(self.folder/'tokenizer.json'));self.tokenizer.no_truncation();self.tokenizer.no_padding()
        empty=self.tokenizer.encode('').ids
        if len(empty)!=2:raise Invalid('语义模型特殊词元格式不匹配')
        self.first,self.last=empty
        specials=json.loads((self.folder/'special_tokens_map.json').read_text('utf-8'));pad=specials.get('pad_token','<pad>')
        if isinstance(pad,dict):pad=pad['content']
        self.pad=self.tokenizer.token_to_id(pad)
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1;options.log_severity_level=3
        self.session=ort.InferenceSession(str(self.folder/'onnx/model_quint8_avx2.onnx'),options,providers=['CPUExecutionProvider'])
        self.inputs={i.name for i in self.session.get_inputs()}
        self.metadata={'version':VERSION,'repository':source['repository'],'revision':source['revision'],'dimension':384,'max_tokens':self.max_tokens,'max_chunks':64,
                       'weights_sha256':source['files']['onnx/model_quint8_avx2.onnx']['sha256'],'pooling':'masked token mean, token-weighted window mean, L2 normalization','frozen':True,'local_only':True}
        self.fingerprint=digest(self.metadata);self.cache=self.folder/'embeddings.sqlite3'
        with closing(self.connect()) as db:db.execute('CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, vector BLOB, chunks INTEGER, truncated INTEGER)')

    def connect(self):return sqlite3.connect(self.cache,timeout=20)

    def encode(self,texts):
        result=[]
        with self.lock:
            for text in texts:
                key=digest({'encoder':self.fingerprint,'text':text})
                if key not in self.memory:
                    with closing(self.connect()) as db:row=db.execute('SELECT vector FROM vectors WHERE id=?',(key,)).fetchone()
                    if row:
                        vector=np.frombuffer(row[0],dtype='<f8').copy()
                        if vector.shape!=(384,) or not np.isfinite(vector).all():raise Invalid('语义向量缓存损坏')
                    else:
                        ids=self.tokenizer.encode(text,add_special_tokens=False).ids;window=self.max_tokens-2;stride=max(1,window-16)
                        windows=[ids[i:i+window] for i in range(0,max(1,len(ids)),stride)]
                        truncated=len(windows)>self.max_chunks;windows=windows[:self.max_chunks]
                        pooled=[];weights=[]
                        for start in range(0,len(windows),8):
                            batch=windows[start:start+8];width=max(len(x)+2 for x in batch)
                            tokens=np.full((len(batch),width),self.pad,dtype=np.int64);mask=np.zeros_like(tokens)
                            for j,part in enumerate(batch):tokens[j,:len(part)+2]=[self.first]+part+[self.last];mask[j,:len(part)+2]=1
                            values={'input_ids':tokens,'attention_mask':mask,'token_type_ids':np.zeros_like(tokens)}
                            hidden=self.session.run(None,{k:v for k,v in values.items() if k in self.inputs})[0]
                            mean=(hidden*mask[:,:,None]).sum(1)/np.maximum(1,mask.sum(1))[:,None]
                            pooled.extend(mean);weights.extend(max(1,len(p)) for p in batch)
                        vector=np.average(np.array(pooled,dtype=np.float64),axis=0,weights=weights)
                        vector/=max(1e-12,float(np.linalg.norm(vector)))
                        if vector.shape!=(384,) or not np.isfinite(vector).all():raise Invalid('语义模型未返回有效向量')
                        with closing(self.connect()) as db:
                            db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)',(key,vector.astype('<f8').tobytes(),len(windows),int(truncated)));db.commit()
                    self.memory[key]=vector
                result.append(self.memory[key])
        return np.stack(result) if result else np.empty((0,384))


def encoder():
    global _instance
    with _instance_lock:
        if _instance is None:
            if not availability()['available']:raise Invalid('请先运行scripts/setup_semantic_encoder.py安装本地语义编码器')
            _instance=SemanticEncoder()
        return _instance
