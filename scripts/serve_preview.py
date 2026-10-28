"""Run updated code against a backup copy while the production service stays up."""
import argparse
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings,SiliconFlow
from ai.service import AIService
from core import Invalid
from server import LocalHTTPServer,make_handler
from store import Store


class ReadOnlySettings:
    def __init__(self,source):self.source=source
    def read(self):return self.source.read()
    def public(self):return {**self.source.public(),'preview_mode':True}
    def key(self):return self.source.key()
    def key_for(self,endpoint):return self.source.key_for(endpoint)
    def save(self,body):raise Invalid('预览复用正式模型配置；请在正式入口管理AI设置')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,default=8766);parser.add_argument('--choice-demo',action='store_true');args=parser.parse_args()
    target=args.db.resolve();production=(ROOT/'data/workbench.sqlite3').resolve()
    if target==production or target.drive.upper()!='D:':raise ValueError('Preview requires a separate D: database')
    target.parent.mkdir(parents=True,exist_ok=True)
    settings=ReadOnlySettings(Settings(ROOT/'data/private'))
    store=Store(target);service=AIService(store,SiliconFlow(settings));service.settings=settings
    if args.choice_demo:
        from ai.choice_demo import seed
        seed(store)
    server=LocalHTTPServer(('127.0.0.1',args.port),make_handler(store,service))
    print(f'Isolated preview: http://127.0.0.1:{args.port}\nData: {target}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();service.close()


if __name__=='__main__':main()
