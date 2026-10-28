"""Conservative checks for explicit numeric requirements, never semantic acceptance."""
import re


def characters(text):
    return len(re.sub(r'\s+|\[M\d+#\d+\]', '', text))


def number(text):
    if text.isdigit():return int(text)
    digits={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if text=='十':return 10
    if '十' in text:
        left,right=text.split('十',1)
        return digits.get(left,1)*10+digits.get(right,0)
    return digits.get(text,0)


def check(task,text):
    result={'method':'explicit-numeric-requirements-v1','warnings':[],
            'note':'仅识别明确数字区间和日序标记；字符按去除空白与素材引用编号后的Unicode字符计，不等同于语义验收。'}
    goal=task.get('brief','')
    lengths=re.findall(r'(\d{1,5})\s*[-–—~～至到]\s*(\d{1,5})\s*(?:个中文字符|中文字符|个字符|字符|个字|字)(?!节)',goal)
    unique={(int(lo),int(hi)) for lo,hi in lengths if 0<int(lo)<=int(hi)}
    if len(unique)==1:
        lo,hi=next(iter(unique));count=characters(text)
        result['length']={'min':lo,'max':hi,'actual':count,'within_range':lo<=count<=hi}
        if not lo<=count<=hi:result['warnings'].append(f'按去除空白与引用编号后的字符计，当前正文为{count}字，不在目标的{lo}–{hi}字范围内，请核对长度。')
    if task.get('category')=='study':
        explicit=goal+'\n'+'\n'.join(task.get('facts',{}).values())
        wanted={number(n) for n in re.findall(r'([一二三四五六七八九十\d]+)天',explicit)}
        if len(wanted)==1 and 1<=next(iter(wanted))<=31:
            days=next(iter(wanted));coverage=set()
            marked='\n'.join(b['title'] for b in task['blocks'] if not b.get('fixed'))+'\n'+text
            for lo,hi in re.findall(r'第([一二三四五六七八九十\d]+)(?:\s*[-–—至到]\s*([一二三四五六七八九十\d]+))?天',marked):
                a,b=number(lo),number(hi) if hi else number(lo)
                if 1<=a<=b<=31:coverage.update(range(a,b+1))
            missing=sorted(set(range(1,days+1))-coverage)
            result['days']={'requested':days,'recognized':sorted(coverage),'not_marked':missing}
            if missing:result['warnings'].append('按“第几天”的明确日序，尚未找到第'+ '、'.join(map(str,missing))+'天；请检查是否已完整安排。其他日期表达可能未被识别。')
    return result
