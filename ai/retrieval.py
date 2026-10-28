"""Small local BM25 index for user-provided source text; never searches the web."""
import math
import re
from collections import Counter

from core import Invalid


def tokens(text):
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]{2,}", lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        words.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return words


def prepare(materials):
    if not isinstance(materials, list) or len(materials) > 10:
        raise Invalid("每次最多附加10份文本素材")
    total = 0
    chunks = []
    for index, material in enumerate(materials):
        if not isinstance(material, dict) or not isinstance(material.get("text"), str) or not isinstance(material.get("name"), str):
            raise Invalid("素材格式不正确")
        text = material["text"].strip()
        total += len(text)
        if len(text) > 40000 or len(material["name"]) > 150 or total > 100000:
            raise Invalid("单份素材最多4万字，总计最多10万字")
        for start in range(0, len(text), 560):
            piece = text[start:start+680]
            if piece:
                mid=material.get('id',f'M{index+1}')
                if not isinstance(mid,str) or not re.fullmatch(r'M[1-9][0-9]*',mid):raise Invalid('素材编号无效')
                chunks.append({"id": f"{mid}#{start//560+1}", "material_id":mid,"name": material["name"], "text": piece})
    return chunks


def retrieve(goal, materials, limit=8):
    chunks = prepare(materials)
    if not chunks:
        return []
    bags = [Counter(tokens(c["text"])) for c in chunks]
    q = set(tokens(goal))
    average = sum(sum(b.values()) for b in bags) / max(1, len(bags))
    frequencies=Counter(word for bag in bags for word in bag)
    for chunk, bag in zip(chunks, bags):
        score = 0.0
        for word in q:
            df = frequencies[word]
            frequency = bag[word]
            if frequency:
                idf = math.log(1 + (len(bags) - df + .5)/(df + .5))
                score += idf * frequency * 2.2 / (frequency + 1.2*(.25+.75*sum(bag.values())/max(1,average)))
        chunk["retrieval_score"] = round(score, 5)
    # Include even zero-match material when the corpus is tiny; disclose it in sources.
    return sorted(chunks, key=lambda c: -c["retrieval_score"])[:limit]
