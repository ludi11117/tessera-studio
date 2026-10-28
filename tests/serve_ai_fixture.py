"""Browser-QA server with a synthetic provider. Never import this in production."""
import argparse
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings,SiliconFlow
from ai.service import AIService
from ai_fixture import fixture_transport
from server import make_handler
from store import Store

parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,default=18767);parser.add_argument('--choice-demo',action='store_true');args=parser.parse_args()
args.db.parent.mkdir(parents=True,exist_ok=True)
os.environ['INTENT_SILICONFLOW_API_KEY']='development-fixture-credential-not-a-real-key'
store=Store(args.db);settings=Settings(args.db.parent/'private');settings.save({'model':'test/fixture-model'})
if args.choice_demo:
    from ai.choice_demo import seed
    seed(store)
service=AIService(store,SiliconFlow(settings,transport=fixture_transport));service.settings=settings
server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,service))
print('QA fixture server ready',flush=True)
try:server.serve_forever()
finally:server.server_close();service.close()
