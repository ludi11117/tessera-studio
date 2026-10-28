"""Bounded model-derived context for revision; predictions never become labels."""
from core import render_variant, variant_for


def revision_context(view,scope):
    model=view.get('model_config',{})
    if not model.get('content_conditioned') or view.get('research_warning') or view['pair_count']<4 or not view.get('ranking'):
        return None
    task,state=view['task'],view['state'];best=view['ranking'][0]
    examples=[]
    for block in task['blocks']:
        bid=block['id']
        if bid in scope and bid not in state['locks']:
            candidate=variant_for(task,bid,best['combo'][bid])
            examples.append({'block':bid,'candidate':candidate['id'],'text':render_variant(task,candidate)[:600]})
    if not examples:return None
    return {'source':'model_prediction_not_human_label','model_id':model['model_id'],
            'model_snapshot_hash':model['snapshot_hash'],'training_pair_hash':model['training_pair_hash'],
            'pair_count':view['pair_count'],'base_revision':view['revision'],'examples':examples,
            'prediction_priorities':model.get('prediction_priorities',{}),
            'instruction':'这些是本任务偏好模型对现有候选的预测，仅供表达与取舍参考，不是用户确认内容。当前明确修改要求、固定事实和锁定约束优先；不要照抄不符合目标的示例，不生成偏好标签。'}
