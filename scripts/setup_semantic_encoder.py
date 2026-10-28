"""Download a pinned public ONNX encoder to D:, never at app startup."""
import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPO='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
WEIGHTS='onnx/model_quint8_avx2.onnx'
WEIGHTS_SHA='98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f'
ROOT=Path(os.environ.get('INTENT_EMBEDDING_HOME','D:/CodexWork/cache/intent-semantic-minilm'))


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen('https://huggingface.co/api/models/'+REPO,timeout=40) as response:info=json.load(response)
    revision=info['sha'];known={f['rfilename'] for f in info['siblings']}
    files=['tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentence_bert_config.json','1_Pooling/config.json','README.md',WEIGHTS]
    if 'LICENSE' in known:files.append('LICENSE')
    manifest={'repository':REPO,'revision':revision,'license':info.get('cardData',{}).get('license'),'files':{},'paid_api_calls':0}
    for name in files:
        target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            temp=target.with_suffix(target.suffix+'.download')
            url=f'https://huggingface.co/{REPO}/resolve/{revision}/{name}'
            print('Downloading '+name,flush=True)
            with urllib.request.urlopen(url,timeout=90) as response,temp.open('wb') as output:
                while chunk:=response.read(1024*1024):output.write(chunk)
            temp.replace(target)
        sha=hashlib.sha256(target.read_bytes()).hexdigest()
        if name==WEIGHTS and sha!=WEIGHTS_SHA:raise RuntimeError('Public encoder checksum mismatch')
        manifest['files'][name]={'sha256':sha,'bytes':target.stat().st_size}
    (ROOT/'source.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'folder':str(ROOT),'revision':revision,'bytes':sum(v['bytes'] for v in manifest['files'].values()),'paid_api_calls':0}),flush=True)


if __name__=='__main__':main()
