"""Interactive-only SiliconFlow smoke check. Never accepts credentials in argv."""
import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai.provider import Settings, SiliconFlow
from ai.service import AIService
from store import Store


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--generate",action="store_true");parser.add_argument("--stored",action="store_true");args=parser.parse_args()
    settings=Settings(ROOT/"data/private")
    if not args.stored:
        key=getpass.getpass("SiliconFlow API Key (hidden): ")
        settings.save({"api_key":key});key=None
    provider=SiliconFlow(settings)
    models=provider.models()
    preference=["Qwen/Qwen3-30B-A3B-Instruct-2507","Qwen/Qwen3-8B","Qwen/Qwen3-14B"]
    selected=next((m for m in preference if m in models),models[0] if models else "")
    settings.save({"model":selected})
    print(json.dumps({"connection":"ok","model_count":len(models),"selected_model":selected,"credential_storage":"Windows DPAPI"}),flush=True)
    if not args.generate:return
    folder=Path("D:/CodexWork/temp/intent-ai-live-check")/str(time.time_ns());folder.mkdir(parents=True)
    service=AIService(Store(folder/"qa.sqlite3"),provider=provider);service.settings=settings
    original_json=provider.json
    call_count=0
    def recorded_json(*args,**kwargs):
        nonlocal call_count
        value,metadata=original_json(*args,**kwargs);call_count+=1
        (folder/f"response-{call_count}.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
        return value,metadata
    provider.json=recorded_json
    job=service.submit("generate",{"goal":"为Python基础学生设计一个两周可完成的图书借阅管理项目，提供功能、实施步骤和验收标准，单机本地运行。","task_type":"project","facts":"周期为两周\n单机本地运行，不购买硬件","materials":[]})
    last=None
    for _ in range(300):
        job=service.public_job(job["id"])
        if job["progress"]!=last:print(json.dumps({"progress":job["progress"]},ensure_ascii=False),flush=True);last=job["progress"]
        if job["status"] not in ("queued","running"):break
        time.sleep(1)
    (folder/"result.json").write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":job["status"],"error":job["error"],"output":str(folder)},ensure_ascii=False),flush=True)
    service.close()
    if job["status"]!="completed":raise SystemExit(1)


if __name__=="__main__":main()
