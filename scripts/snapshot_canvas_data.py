"""Read-only logical fingerprints and optional SQLite online backups; no keys."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot(folder, backup=False):
    result = {}
    for group, directory in [('production', ROOT/'data'), ('preview', Path('D:/CodexWork/temp/intent-v7-preview-20261027'))]:
        tables = {}
        for name in ['workbench.sqlite3', 'assistant.sqlite3', 'learning.sqlite3']:
            file = directory/name
            if not file.exists():continue
            with sqlite3.connect(file.as_uri()+'?mode=ro', uri=True) as db:
                db.execute('BEGIN')
                names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                summary = {}
                for table in names:
                    quoted='"'+table.replace('"','""')+'"'
                    rows = [json.dumps(r,ensure_ascii=False,default=lambda v:v.hex() if isinstance(v,bytes) else str(v)) for r in db.execute('SELECT * FROM '+quoted)]
                    summary[table]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()}
                    if table in ['jobs', 'runs']:
                        columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
                        if 'status' in columns:
                            active=db.execute('SELECT COUNT(*) FROM '+quoted+" WHERE status IN ('queued','running','cancelling')").fetchone()[0]
                            summary[table]['active']=active
                            if active:raise RuntimeError('Active jobs; do not restart: '+group+'/'+name)
                if backup:
                    destination=folder/group/name;destination.parent.mkdir(parents=True,exist_ok=True)
                    with sqlite3.connect(destination) as target:db.backup(target)
                tables[name]=summary
        result[group]=tables
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['before','after']);p.add_argument('--folder',type=Path,required=True);a=p.parse_args()
    if a.folder.resolve().drive.upper()!='D:':raise ValueError('D: required')
    a.folder.mkdir(parents=True,exist_ok=True)
    result=snapshot(a.folder,a.phase=='before')
    target=a.folder/(a.phase+'.json');target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if a.phase=='after':
        before=json.loads((a.folder/'before.json').read_text(encoding='utf-8'))
        if before!=result:raise RuntimeError('Business tables changed; inspect fingerprints')
    print(json.dumps({'phase':a.phase,'file':str(target),'tables':sum(len(ts) for group in result.values() for ts in group.values()),'active':0,'unchanged':a.phase=='after'}))
