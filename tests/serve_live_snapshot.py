"""Read-only preview of an isolated, actual-provider QA session. No paid calls."""
import argparse
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings
from ai.service import AIService
from server import make_handler
from store import Store

parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--port',type=int,default=18768);args=parser.parse_args()
folder=args.folder.resolve()
if not any(str(folder).lower().startswith(p) for p in ('d:\\codexwork\\temp\\intent-ai-live-check\\','d:\\codexwork\\temp\\intent-readiness-live\\')):raise SystemExit('Use an isolated live-check folder')
store=Store(folder/'qa.sqlite3');service=AIService(store);service.settings=Settings(ROOT/'data/private')
Base=make_handler(store,service)
class ReadOnly(Base):
    def do_POST(self):self.respond({'error':'Read-only QA preview'},403)
server=ThreadingHTTPServer(('127.0.0.1',args.port),ReadOnly)
print('Read-only QA preview ready',flush=True)
try:server.serve_forever()
finally:server.server_close();service.close()
