"""SQLite transactions, append-only audit records, optimistic revisions."""
import copy
import json
import re
import sqlite3
import uuid
import importlib.util
from pathlib import Path
from contextlib import closing, contextmanager
from datetime import datetime, timezone

from core import MODEL_CONFIG, Invalid, comparison, enumerate_feasible, feasible, feature_keys, fit, initial_state, recommendations, render, validate_task, variant_for
from samples import SAMPLES


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class Conflict(Invalid):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._learning_service=None
        import threading
        self._learning_lock=threading.RLock()
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, task TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, before_state TEXT, after_state TEXT, revision INTEGER NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS session_events ON events(session, seq);
                CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY, session TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL);
            """)
            if not db.execute("SELECT 1 FROM sessions LIMIT 1").fetchone():
                for sample in SAMPLES:
                    self._create(db, sample)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, sid, kind, payload, rev, before=None, after=None):
        eid = uuid.uuid4().hex
        db.execute("INSERT INTO events(id,session,kind,payload,before_state,after_state,revision,created) VALUES(?,?,?,?,?,?,?,?)",
                   (eid, sid, kind, dump(payload), dump(before) if before is not None else None, dump(after) if after is not None else None, rev, now()))
        return eid

    def _create(self, db, task):
        validate_task(task)
        task = copy.deepcopy(task)
        for b in task["blocks"]:
            b.pop("archive", None)  # Imported candidate libraries start a new, independent session.
        sid = uuid.uuid4().hex
        state = initial_state(task)
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (sid, dump(task), dump(state), 0, now()))
        self.event(db, sid, "created", {"source": task.get("source", "example")}, 0)
        return sid

    def create(self, task):
        with self.transaction() as db:
            return self._create(db, task)

    def sessions(self):
        with closing(self.connect()) as db:
            return [{"id": r["id"], "title": json.loads(r["task"])["title"], "source": json.loads(r["task"]).get("source", "example"), "revision": r["revision"], "created": r["created"]} for r in db.execute("SELECT * FROM sessions ORDER BY created DESC")]

    def load(self, db, sid):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise Invalid("会话不存在")
        return json.loads(row["task"]), json.loads(row["state"]), row["revision"]

    def events(self, db, sid):
        return [{**dict(r), "payload": json.loads(r["payload"]), "before_state": json.loads(r["before_state"]) if r["before_state"] else None, "after_state": json.loads(r["after_state"]) if r["after_state"] else None} for r in db.execute("SELECT * FROM events WHERE session=? ORDER BY seq", (sid,))]

    def active(self, events):
        retracted = {e["payload"]["target"] for e in events if e["kind"] == "undo"}
        retracted.update(e['payload']['target'] for e in events if e['kind']=='feedback_retract' and e['id'] not in retracted)
        return [e for e in events if e["id"] not in retracted]

    def learning(self):
        with self._learning_lock:
            if self._learning_service is None:
                from ai.learning import LearningService
                self._learning_service=LearningService(self)
            return self._learning_service

    def trained_model(self,sid,task,state,pairs):
        return self.learning().model_for(sid,task,state,pairs) if state.get('learning_active') else None

    def view(self, sid):
        with closing(self.connect()) as db:
            task, state, rev = self.load(db, sid)
            events = self.events(db, sid)
            active = self.active(events)
            pairs = [e["payload"] for e in active if e["kind"] == "compare"]
            weights = fit(task, pairs)
            weight_map = dict(zip(feature_keys(task), weights))
            ranks, count = recommendations(task, state, weights)
            ui_weights = [{"block": b["title"], "variant": i + 1, "weight": round(weight_map[(b["id"], v["id"])], 4)} for b in task["blocks"] for i, v in enumerate(b["variants"])]
            model_config = MODEL_CONFIG
            research_warning = None
            trained=self.trained_model(sid,task,state,pairs)
            if trained:
                from research.integration import view_model
                ranks,count,ui_weights,model_config=view_model(task,state,pairs,limit=None,trained=trained)
            elif state.get("research"):
                try:
                    from research.integration import view_model
                    ranks, count, ui_weights, model_config = view_model(task, state, pairs, limit=None)
                except ImportError:
                    research_warning = "研究环境不可用，当前预览使用V1基线。请用启动研究工作台.cmd继续研究模式。"
            unlimited = {**state, "max_chars": None, "acceptance": None}
            shortest = min((len(render(task, c)) for c in enumerate_feasible(task, unlimited)), default=None)
            evaluated = next((e["payload"]["winner"] for e in reversed(active) if e["kind"] == "compare" and e["payload"].get("response_mode") == "evaluate_only"), None)
            optimization = None
            if state.get('acceptance',{}).get('confirmed'):
                from ai.acceptance import evaluate,digest
                structural=enumerate_feasible(task,{**state,'acceptance':None})
                rejected={}
                for combo in structural:
                    for failure in evaluate(task,combo,state['acceptance'])['failures']:
                        rejected[failure['label']]=rejected.get(failure['label'],0)+1
                optimization={'method':'exhaustive-confirmed-constraints-then-preference-v1','searched':len(structural),'eligible':count,
                              'rejected_by_requirement':rejected,'pair_count':len(pairs),'contract_hash':digest(state['acceptance']),
                              'objective':'task_local_preference_score_then_fewest_changes','semantic_fact_check':'not_performed'}
            from ai.options import board
            choice_board=board(task,state,ranks,len(pairs))
            learning_status=self.learning().summary(sid)
            if state.get('learning_active') and trained is None:
                learning_status.update(active_run=None,active_kind=None,stale=True,warning='当前反馈、权重或依赖无法与该训练版本一致验证，已回退到其他可用推荐方式。')
                for run in learning_status['runs']:run['active']=False
            return {"id": sid, "task": task, "state": state, "revision": rev, "text": render(task, state["combo"]),'choice_board':choice_board,
                    "ranking": ranks[:5], "feasible_count": count, "pair_count": len(pairs), "model_config": model_config,'optimization':optimization,
                    "weights": ui_weights, "research_available": importlib.util.find_spec("numpy") is not None, "research_warning": research_warning,'learning':learning_status,
                    "constraint_diagnostics": {"minimum_chars_under_locks": shortest, "max_chars": state["max_chars"]},
                    "last_evaluated": {"combo": evaluated, "text": render(task, evaluated), "can_apply": feasible(task, evaluated, state)} if evaluated else None,
                    "history": [{"id": e["id"], "kind": e["kind"], "time": e["created"], "revision": e["revision"], "retracted": e not in active} for e in events[-60:]],
                    "can_undo": any(e["before_state"] is not None and e["kind"] != "undo" for e in active),
                    "last_export": next((e["payload"].get("path") for e in reversed(events) if e["kind"] == "export"), None)}

    def write_export(self, task, extension, content):
        folder = Path(self.path).resolve().parent / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', task["title"])[:60]
        path = folder / f"{title}-{uuid.uuid4().hex[:10]}.{extension}"
        path.write_text(content, encoding="utf-8", newline="\n")
        return str(path)

    def options(self,sid,body):
        from ai.options import inspect
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            task,state,rev=self.load(db,sid)
            if type(body.get('revision')) is not int or body['revision']!=rev:raise Conflict('稿件已更新，请先刷新后再组合')
            pairs=[e['payload'] for e in self.active(self.events(db,sid)) if e['kind']=='compare']
        trained=self.trained_model(sid,task,state,pairs)
        if trained:
            from research.integration import view_model
            ranks,_,_,_=view_model(task,state,pairs,limit=None,trained=trained)
        elif state.get('research'):
            try:
                from research.integration import view_model
                ranks,_,_,_=view_model(task,state,pairs,limit=None)
            except ImportError:ranks,_=recommendations(task,state,fit(task,pairs))
        else:ranks,_=recommendations(task,state,fit(task,pairs))
        baseline_count=len(ranks);trial=None
        if 'trial_contract' in body:
            from ai.acceptance import validate
            contract=validate(body['trial_contract']);state={**state,'acceptance':contract}
            if trained or state.get('research'):
                try:
                    from research.integration import view_model
                    ranks,_,_,_=view_model(task,state,pairs,limit=None,trained=trained)
                except ImportError:ranks,_=recommendations(task,state,fit(task,pairs))
            else:ranks,_=recommendations(task,state,fit(task,pairs))
            trial={'contract':contract,'original_eligible':baseline_count,'eligible':len(ranks),'adoption_requires_confirmation':True}
        return {'revision':rev,**inspect(task,state,ranks,body.get('combo',state['combo']),body.get('anchors',{}),len(pairs)),'trial':trial}

    def decision(self, sid, revision, materials=None):
        """A revision-bound read snapshot; never creates events or labels."""
        from ai.decision import analyze
        from ai.delivery import check
        from ai.acceptance import digest
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            task, state, rev = self.load(db, sid)
            if type(revision) is not int or revision != rev:
                raise Conflict('稿件已更新，请重新计算本版本的决策证据')
            pairs = [e['payload'] for e in self.active(self.events(db, sid)) if e['kind'] == 'compare']
        trained = self.trained_model(sid, task, state, pairs)
        model_config = MODEL_CONFIG
        ranks, _ = recommendations(task, state, fit(task, pairs))
        warning = None
        if trained or state.get('research'):
            try:
                from research.integration import view_model
                ranks, _, _, model_config = view_model(task, state, pairs, limit=None, trained=trained)
            except ImportError:
                warning = '研究依赖不可用，本次按版本偏好基线分析。'
        if state.get('learning_active') and trained is None:
            warning = '当前反馈、权重或依赖与训练版本不一致，使用其他可用推荐方式。'
        view = {'id': sid, 'task': task, 'state': state, 'revision': rev}
        materials = task.get('materials', []) if materials is None else materials
        delivery = check(view, materials)
        stability = None
        if trained:
            from research.decision_value import model_risk
            stability = model_risk(trained, enumerate_feasible(task, state))
        return {'session': sid, 'revision': rev, 'warning': warning, **analyze(task, state, ranks, len(pairs), model_config),
                'stability': stability, 'delivery': delivery, 'snapshot': {'task_hash': digest(task), 'state_hash': digest(state),
                'contract_hash': digest(state.get('acceptance')), 'materials_hash': digest(materials), 'document_hash': digest(render(task, state['combo']))}}

    def requirement_evidence(self,sid,body):
        from ai.requirement_trace import snapshot,semantic_evidence
        with closing(self.connect()) as db:
            db.execute('BEGIN');task,state,rev=self.load(db,sid)
        if type(body.get('revision')) is not int or rev!=body['revision']:raise Conflict('稿件已变化，请重新核对')
        snap=snapshot(task,state)
        if body.get('snapshot_hash')!=snap['hash']:raise Conflict('需求或素材已变化，请重新核对')
        row=next((r for r in snap['requirements'] if r['id']==body.get('requirement') and r['kind']=='intent'),None)
        if not row:raise Invalid('请选择一项明确需求查找线索')
        result=semantic_evidence(row['text'],snap['sections'])
        with closing(self.connect()) as db:
            if self.load(db,sid)[2]!=rev:raise Conflict('查找期间稿件已更新，请重新核对')
        return {'revision':rev,'snapshot_hash':snap['hash'],'requirement':row['id'],'paid_calls':0,**result}

    def action(self, sid, body, ai_metadata=None, initial_materials=None):
        with self.transaction() as db:
            task, state, rev = self.load(db, sid)
            if type(body.get("revision")) is not int or body["revision"] != rev:
                raise Conflict("此会话已在其他窗口更新，已重新载入。请核对后重试。")
            kind = body.get("kind")
            before = copy.deepcopy(state)
            original_text=render(task,state['combo'])
            original_titles=[b['title'] for b in task['blocks']]
            events = self.events(db, sid)
            active = self.active(events)
            payload = {}
            if kind == "select":
                bid, vid = body.get("block"), body.get("variant")
                variant_for(task, bid, vid)
                if bid in state["locks"] and state["locks"][bid] != vid:
                    raise Invalid("请先解锁该段落")
                combo = {**state["combo"], bid: vid}
                if not feasible(task, combo, state):
                    raise Invalid("该选择不满足当前验收、锁定或长度约束，请核对后调整")
                payload = {"block": bid, "variant": vid, "context": state["combo"], "training_label": False}
                state["combo"] = combo
            elif kind == "lock":
                bid = body.get("block")
                if bid not in state["combo"]:
                    raise Invalid("部件不存在")
                if any(b["id"]==bid and b.get("fixed") for b in task["blocks"]):
                    raise Invalid("这是创建任务时确定的固定事实，不能解锁；改变事实请新建任务")
                if bid in state["locks"]:
                    del state["locks"][bid]
                else:
                    state["locks"][bid] = state["combo"][bid]
                payload = {"block": bid, "locked": bid in state["locks"]}
            elif kind == "constraint":
                limit = body.get("max_chars")
                if limit is not None and (type(limit) is not int or not 1 <= limit <= 20000):
                    raise Invalid("字数上限应为1–20000的整数，或留空")
                state["max_chars"] = limit
                payload = {"max_chars": limit}
            elif kind == 'requirement_answer':
                from ai.requirement_trace import snapshot
                snap=snapshot(task,state)
                if body.get('snapshot_hash')!=snap['hash']:raise Conflict('需求或正文已变化，请重新补充')
                row=next((r for r in snap['requirements'] if r['id']==body.get('requirement') and r['kind']=='unknown'),None)
                answer=body.get('answer','')
                if not row or not isinstance(answer,str) or not 1<=len(answer.strip())<=500:raise Invalid('请为当前待确认问题补充1–500字信息')
                previous=copy.deepcopy(task['intent_brief']);brief=task['intent_brief']
                brief['unresolved']=[q for q in brief.get('unresolved',[]) if q!=row['text']]
                brief['explicit_answers']=[a for a in brief.get('explicit_answers',[]) if a['question']!=row['text']]+[{'question':row['text'],'answer':answer.strip()}]
                state['review']={}
                payload={'previous_intent_brief':previous,'question':row['text'],'answer':answer.strip(),'training_label':False}
            elif kind == 'requirement_review':
                from ai.requirement_trace import review
                state['requirement_reviews']=review(task,state,body)
                if body.get('decision')=='gap':state['review']={}
                payload={k:body.get(k) for k in ('requirement','snapshot_hash','decision','blocks','note')}
                payload['training_label']=False
            elif kind == 'preserve_fragment':
                from ai.preservation import update
                if type(body.get('remove',False)) is not bool:raise Invalid('局部保留操作无效')
                state['preserved_fragments'] = update(task, state, body.get('block'), body.get('text'), body.get('remove',False))
                state['review'] = {};state.pop('final',None)
                payload = {'block':body['block'],'text':body['text'].strip(),'remove':body.get('remove',False),'training_label':False}
            elif kind == 'acceptance':
                from ai.acceptance import validate
                state['acceptance'] = validate(body.get('contract'))
                state['review'] = {}
                payload = {'contract': state['acceptance'], 'training_label': False}
            elif kind == "research_config":
                config = body.get("config")
                if not isinstance(config, dict) or config.get("model") not in ("legacy", "additive", "interaction", "content_linear", "content_frozen", "content_neural") or config.get("policy") not in ("random", "uncertainty", "kg", "cost_kg") or config.get("context_mode") not in ("current", "mixed"):
                    raise Invalid("研究模型或比较策略配置无效")
                if not importlib.util.find_spec("numpy"):
                    raise Invalid("需要可选研究环境，请运行setup-research.ps1后使用启动研究工作台.cmd")
                if type(config.get("budget")) is not int or not 0 <= config["budget"] <= 100 or type(config.get("seed")) is not int or not 0 <= config["seed"] <= 2147483647 or type(config.get("evaluate_only")) is not bool:
                    raise Invalid("预算需为0–100，种子需为非负整数，并明确是否只评价")
                if config.get("data_origin") not in ("unclassified", "user_use_self_reported", "development_test", "simulation"):
                    raise Invalid("请选择数据来源")
                participant = config.get("participant_id", "")
                if not isinstance(participant, str) or (participant and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", participant)):
                    raise Invalid("匿名参与者编号只接受1–40位英文、数字、下划线或连字符")
                state["research"] = {k: config[k] for k in ("model", "policy", "context_mode", "budget", "seed", "evaluate_only", "data_origin")}
                state["research"].update({"participant_id": participant or None, "l2_sum": 0.5, "pool_limit": 12, "planning_ms": 1000})
                state.pop('learning_active',None)
                payload = {"schema_version": 2, "config": state["research"], "training_label": False}
            elif kind=='learning_activate':
                rid=body.get('run')
                if not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9]{32}',rid):raise Invalid('训练版本编号无效')
                pairs=[e['payload'] for e in active if e['kind']=='compare']
                training_row=self.learning().validate_activation(sid,rid,task,pairs)
                state['learning_active']=rid
                model_kind=body.get('model_kind','semantic_deep')
                if model_kind not in ('semantic_deep','semantic_linear'):raise Invalid('本地训练模型类型无效')
                state['learning_kind']=model_kind
                if model_kind=='semantic_deep':state['learning_priorities']={k:v for k,v in state.get('learning_priorities',{}).items() if training_row['report']['reason_counts'].get(k,0)}
                payload={'run':rid,'model_kind':model_kind,'training_label':False}
            elif kind=='learning_priorities':
                from ai.learning import REASONS
                values=body.get('priorities')
                if not isinstance(values,dict) or set(values)-set(REASONS) or any(type(v) not in (int,float) or not 0<=v<=2 for v in values.values()):raise Invalid('偏好维度权重需为0–2')
                pairs=[e['payload'] for e in active if e['kind']=='compare'];model=self.trained_model(sid,task,state,pairs)
                if model is None:raise Invalid('请先启用与当前反馈一致的训练版本')
                if model.metadata()['model_id']=='semantic_linear' and any(values.values()):raise Invalid('语义线性对照只使用整体偏好；切回深度网络后可调整理由侧重')
                if any(v and not model.report['reason_counts'].get(k,0) for k,v in values.items()):raise Invalid('该维度尚无训练理由，不能当作已学会的偏好')
                state['learning_priorities']=values;payload={'priorities':values,'training_label':False}
            elif kind=='feedback_retract':
                target=next((e for e in active if e['id']==body.get('target') and e['kind']=='compare'),None)
                if not target:raise Invalid('这条反馈不存在或已撤回')
                payload={'target':target['id'],'training_label':False}
            elif kind in ('apply','customize'):
                combo = body.get("combo")
                if not isinstance(combo, dict) or not feasible(task, combo, state):
                    raise Invalid("组合不满足已确认验收、锁定或字数约束，未作更改")
                state["combo"] = combo
                payload = {"combo": combo, "training_label": False}
                if kind=='customize':
                    from ai.options import anchors_for
                    anchors=anchors_for(task,body.get('anchors',{}))
                    if any(combo[k]!=v for k,v in anchors.items()):raise Invalid('保留项必须与采用的方案一致')
                    state['locks'].update(anchors)
                    payload['anchors']=anchors
            elif kind=='option_save':
                from ai.options import anchors_for,describe
                from ai.acceptance import digest
                name=body.get('name','')
                if not isinstance(name,str) or not 1<=len(name.strip())<=50:raise Invalid('备选方案名称应为1–50字')
                saved=state.setdefault('saved_options',[])
                if len(saved)>=6:raise Invalid('本任务最多收藏6份备选，请先移除不需要的方案')
                info=describe(task,state,body.get('combo'))
                if any(info['combo'].get(k)!=v for k,v in state['locks'].items()):raise Invalid('备选方案不能更改已锁定部分')
                anchors=anchors_for(task,body.get('anchors',{}))
                if any(info['combo'][k]!=v for k,v in anchors.items()):raise Invalid('备选保留项与方案不符')
                item={'id':uuid.uuid4().hex,'name':name.strip(),'combo':info['combo'],'anchors':anchors,'sections':info['sections'],
                      'contract_hash':info['acceptance']['contract_hash'],'materials_hash':digest(task.get('materials',[])),'created':now(),'base_revision':rev}
                saved.append(item);payload={'option':item,'training_label':False}
            elif kind=='option_delete':
                oid=body.get('option');saved=state.get('saved_options',[])
                if not any(o['id']==oid for o in saved):raise Invalid('备选方案不存在')
                state['saved_options']=[o for o in saved if o['id']!=oid]
                payload={'option':oid,'training_label':False}
            elif kind == 'review':
                checks=body.get('checks')
                if not isinstance(checks,dict) or set(checks)!={'read_through','facts_checked','usable'} or any(type(v) is not bool for v in checks.values()):raise Invalid('交付检查项无效')
                if checks['usable']:
                    from ai.requirement_trace import report
                    if report(task,state)['counts'].get('user_gap'):raise Invalid('还有明确需求被标记为缺口，请先处理或重新核对，再确认可用')
                state['review']=checks
                payload={'checks':checks,'training_label':False}
            elif kind == "materials":
                from ai.materials import reconcile
                previous=task.get('materials',initial_materials or [])
                library,counter=reconcile(body.get('materials'),previous,task.get('material_counter',0))
                if library==previous:raise Invalid('素材没有变化')
                payload={'previous_materials':copy.deepcopy(task.get('materials')),'material_ids':[m['id'] for m in library],'training_label':False}
                task['materials']=library;task['material_counter']=counter
            elif kind == "edit":
                blocks = body.get("blocks")
                if not isinstance(blocks, list) or len(blocks) != len(task["blocks"]):
                    raise Invalid("已有任务的部件结构不能改变；请新建任务导入新的结构")
                previous = [{"id": b["id"], "title": b["title"], "variants": copy.deepcopy(b["variants"])} for b in task["blocks"]]
                changes = []
                for b, incoming in zip(task["blocks"], blocks):
                    if not isinstance(incoming, dict) or incoming.get("id") != b["id"] or not isinstance(incoming.get("variants"), list) or len(incoming["variants"]) != 3:
                        raise Invalid("段落ID或候选数量不匹配")
                    if incoming.get('title')!=b['title'] and b['id'] in state['locks']:
                        raise Invalid('不能修改已锁定章节的标题；请先解锁')
                    b["title"] = incoming.get("title")
                    for i, v in enumerate(incoming["variants"]):
                        old = b["variants"][i]
                        if not isinstance(v, dict) or v.get("id") != old["id"]:
                            raise Invalid("候选版本已发生变化，请重新打开编辑器")
                        if v.get("template") != old["template"]:
                            if state["locks"].get(b["id"]) == old["id"]:
                                raise Invalid("不能编辑已锁定的段落版本；请先解锁")
                            b.setdefault("archive", []).append(copy.deepcopy(old))
                            new = {**old, "id": f"{b['id']}-r{uuid.uuid4().hex[:12]}", "template": v.get("template")}
                            b["variants"][i] = new
                            changes.append({"block": b["id"], "old": old["id"], "new": new["id"]})
                            if state["combo"][b["id"]] == old["id"]:
                                state["combo"][b["id"]] = new["id"]
                validate_task(task)
                if not changes and all(b["title"] == p["title"] for b, p in zip(task["blocks"], previous)):
                    raise Invalid("候选没有变化")
                if not feasible(task, state["combo"], {**state, 'acceptance': None}):
                    raise Invalid("编辑后的当前组合违反长度、锁定或局部原文保留要求；请先核对约束")
                payload = {"changes": changes, "previous_blocks": previous, "training_label": False}
                if ai_metadata is not None:
                    payload["previous_ai"] = copy.deepcopy(task.get("ai"))
                    payload["ai_provenance"] = ai_metadata
                    info = task.setdefault("ai", {})
                    info["sources"] = list({s["id"]: s for s in info.get("sources", []) + ai_metadata.get("sources", [])}.values())
                    info.setdefault("revisions", []).append({k:v for k,v in ai_metadata.items() if k != "sources"})
            elif kind in ("compare", "skip"):
                row = db.execute("SELECT * FROM offers WHERE id=? AND session=?", (body.get("offer"), sid)).fetchone()
                if not row or row["revision"] != rev or row["status"] != "pending":
                    raise Conflict("比较已过期或已回答，请重新获取")
                offer = json.loads(row["payload"])
                if kind == "compare":
                    choice = body.get("choice")
                    if choice not in ("a", "b"):
                        raise Invalid("请明确选择A或B")
                    from ai.learning import REASONS
                    reasons=body.get('reasons',[]);note=body.get('reason_note','')
                    if not isinstance(reasons,list) or len(reasons)>2 or any(not isinstance(r,str) or r not in REASONS for r in reasons) or len(set(reasons))!=len(reasons):raise Invalid('请选择最多两项比较理由')
                    if not isinstance(note,str) or len(note)>300:raise Invalid('补充理由最多300字')
                    winner, loser = offer[choice], offer["b" if choice == "a" else "a"]
                    if not feasible(task, winner, state) or not feasible(task, loser, state):
                        raise Conflict("比较已不满足当前约束")
                    mode = offer.get("response_mode", "adopt_winner")
                    payload = {"schema_version": 2, "offer": body["offer"], "block": offer["block"], "key": offer["key"], "winner": winner, "loser": loser, "context": offer.get('context',{k:v for k,v in offer["a"].items() if k != offer["block"]}), "current_combo_at_response": before["combo"], "choice": choice, "training_label": True, "response_mode": mode}
                    if offer.get('comparison_kind')=='whole_plan':payload['comparison_kind']='whole_plan'
                    payload.update(reasons=reasons,reason_note=note.strip())
                    if mode == "adopt_winner":
                        state["combo"] = winner
                else:
                    payload = {"offer": body["offer"], "key": offer["key"], "training_label": False}
                db.execute("UPDATE offers SET status=? WHERE id=?", (kind, body["offer"]))
            elif kind == "undo":
                targets = [e for e in active if e["before_state"] is not None and e["kind"] != "undo"]
                if not targets:
                    raise Invalid("没有可撤回的操作")
                target = targets[-1]
                state = target["before_state"]
                if target['kind']=='requirement_answer':task['intent_brief']=target['payload']['previous_intent_brief']
                if target['kind']=='materials':
                    old_library=target['payload']['previous_materials']
                    if old_library is None:task.pop('materials',None)
                    else:task['materials']=old_library
                if target["kind"] == "edit":
                    for b, old in zip(task["blocks"], target["payload"]["previous_blocks"]):
                        all_versions = {v["id"]: v for v in b["variants"] + b.get("archive", [])}
                        active_ids = {v["id"] for v in old["variants"]}
                        b["archive"] = [v for vid, v in all_versions.items() if vid not in active_ids]
                        b["variants"] = copy.deepcopy(old["variants"])
                        b["title"] = old["title"]
                    if "previous_ai" in target["payload"]:
                        if target["payload"]["previous_ai"] is None:
                            task.pop("ai", None)
                        else:
                            task["ai"] = copy.deepcopy(target["payload"]["previous_ai"])
                payload = {"target": target["id"], "kind": target["kind"]}
            elif kind == "adopt":
                if not feasible(task, state["combo"], state):
                    raise Invalid("当前组合超出约束，不能最终采用")
                state["final"] = {"text": render(task, state["combo"]), "combo": copy.deepcopy(state["combo"]), "time": now()}
                payload = copy.deepcopy(state["final"])
            elif kind == "export":
                if not feasible(task, state["combo"], state):
                    raise Invalid("当前组合不满足约束，请先调整后导出")
                text = render(task, state["combo"])
                path = self.write_export(task, "txt", text)
                self.event(db, sid, "export", {"combo": state["combo"], "text": text, "path": path}, rev)
                return {"text": text, "title": task["title"], "path": path}
            elif kind == "audit_export":
                audit = {"schema_version": 2, "session_id": sid, "model_config": state.get("research", MODEL_CONFIG), "exported_at": now(), "task": task, "state": state, "revision": rev, "events": events,
                         "note": "仅明确compare事件生成标签，undo撤回后排除；预置候选内容为示例。"}
                path = self.write_export(task, "json", json.dumps(audit, ensure_ascii=False, indent=2))
                self.event(db, sid, "audit_export", {"path": path}, rev)
                return {"path": path}
            elif kind == "exposure":
                self.event(db, sid, "exposure", {"combo": state["combo"], "initial_candidates": [{b["id"]: b["variants"][i]["id"] for b in task["blocks"]} for i in range(3)]}, rev)
                return {"ok": True}
            elif kind == "recommend":
                pairs=[e['payload'] for e in active if e['kind']=='compare']
                weights = fit(task, pairs)
                ranks, count = recommendations(task, state, weights)
                trained=self.trained_model(sid,task,state,pairs)
                if trained:
                    from research.integration import view_model
                    ranks,count,_,_=view_model(task,state,pairs,trained=trained)
                elif state.get("research"):
                    try:
                        from research.integration import view_model
                        ranks, count, _, _ = view_model(task, state, [e["payload"] for e in active if e["kind"] == "compare"])
                    except ImportError:
                        raise Invalid("研究环境不可用，请使用启动研究工作台.cmd")
                self.event(db, sid, "recommendation_exposure", {"ranking": ranks[:5], "feasible_count": count}, rev)
                return {"ok": True}
            else:
                raise Invalid("未知操作")
            if kind!='undo' and (render(task,state['combo'])!=original_text or [b['title'] for b in task['blocks']]!=original_titles or kind=='materials'):
                state['review']={}
            if kind not in ("adopt", "undo", "skip", "research_config",'option_save','option_delete','learning_activate','learning_priorities','feedback_retract') and not (kind == "compare" and payload.get("response_mode") == "evaluate_only"):
                state["final"] = None
            rev += 1
            self.event(db, sid, kind, payload, rev, before, state)
            db.execute("UPDATE sessions SET task=?,state=?,revision=? WHERE id=?", (dump(task), dump(state), rev, sid))
            db.execute("UPDATE offers SET status='stale' WHERE session=? AND status='pending'", (sid,))
            return {"ok": True}

    def offer(self, sid, revision):
        with self.transaction() as db:
            task, state, rev = self.load(db, sid)
            if revision != rev:
                raise Conflict("状态已更新，请重试")
            existing = db.execute("SELECT id,payload FROM offers WHERE session=? AND revision=? AND status='pending'", (sid, rev)).fetchone()
            if existing:
                return {"id": existing["id"], **json.loads(existing["payload"])}
            active = self.active(self.events(db, sid))
            pairs = [e["payload"] for e in active if e["kind"] == "compare"]
            weights = fit(task, pairs)
            seen = {e["payload"]["key"] for e in active if e["kind"] in ("compare", "skip")}
            trained=self.trained_model(sid,task,state,pairs)
            if trained and (not state.get('research') or len(pairs)<state['research']['budget']):
                result=self.learning().offer(sid,task,{**state,'_revision':rev},pairs,seen)
            elif state.get("research"):
                try:
                    from research.integration import make_offer
                    result, stopped = make_offer(task, state, pairs, seen, rev)
                except ImportError:
                    raise Invalid("研究环境不可用，请使用启动研究工作台.cmd")
                if result is None:
                    self.event(db, sid, "query_stop", {"schema_version": 2, **stopped}, rev)
            else:
                result = comparison(task, state, weights, seen)
            if not result and state.get('acceptance',{}).get('confirmed') and (not state.get('research') or len(pairs)<state['research']['budget']):
                from ai.options import distance
                from core import pair_key,sigmoid
                if trained:
                    from research.integration import view_model
                    ranks,_,_,_=view_model(task,state,pairs,limit=None,trained=trained)
                elif state.get('research'):
                    try:
                        from research.integration import view_model
                        ranks,_,_,_=view_model(task,state,pairs,limit=None)
                    except ImportError:ranks,_=recommendations(task,state,weights)
                else:ranks,_=recommendations(task,state,weights)
                choices=[]
                for i,a in enumerate(ranks[:24]):
                    for z in ranks[i+1:24]:
                        key=pair_key('__whole__',a['combo'],z['combo'])
                        if key not in seen:choices.append((abs(a['score']-z['score']),-distance(task,a['combo'],z['combo']),key,a,z))
                if choices:
                    _,_,key,a,z=min(choices,key=lambda c:c[:3])
                    changed=[b['id'] for b in task['blocks'] if a['combo'][b['id']]!=z['combo'][b['id']]]
                    result={'block':'__whole__','comparison_kind':'whole_plan','title':'完整方案','a':a['combo'],'b':z['combo'],
                            'context':{k:v for k,v in a['combo'].items() if k not in changed},'changed_blocks':changed,'key':key,
                            'probability_a':round(sigmoid(a['score']-z['score']),5),'response_mode':'evaluate_only','alternative_context':True,
                            'planning':{'method':'feasible-whole-plan-fallback','pool_limit':24,'note':'完整组合比较，不使用原单章KG策略。'}}
            if not result:
                return None
            from research.dataset import sha
            settings = state.get("research", {})
            result["snapshot"] = {"schema_version": 2, "session_id": sid, "task_revision": rev, "constraint_revision": rev,
                                  "task_hash": sha(task), "constraint_hash": sha({"locks": state["locks"], "max_chars": state["max_chars"], **({'acceptance':state['acceptance']} if state.get('acceptance') else {})}),
                                  "data_origin": settings.get("data_origin", "unclassified"), "participant_id": settings.get("participant_id"),
                                  "texts": {"a": render(task, result["a"]), "b": render(task, result["b"])},
                                  "model_config": settings or MODEL_CONFIG}
            if trained:result['snapshot']['model_config']=trained.metadata()
            if state.get('acceptance'):result['snapshot']['acceptance']=copy.deepcopy(state['acceptance'])
            oid = uuid.uuid4().hex
            db.execute("INSERT INTO offers VALUES(?,?,?,?,?)", (oid, sid, rev, dump(result), "pending"))
            self.event(db, sid, "comparison_exposure", {"offer": oid, **result}, rev)
            return {"id": oid, **result}

    def audit(self, sid):
        with closing(self.connect()) as db:
            task, state, rev = self.load(db, sid)
            return {"schema_version": 2, "session_id": sid, "model_config": state.get("research", MODEL_CONFIG), "exported_at": now(), "task": task, "state": state, "revision": rev, "events": self.events(db, sid), "note": "示例内容不代表真实用户实验；仅明确compare事件生成标签，undo撤回后排除。"}
