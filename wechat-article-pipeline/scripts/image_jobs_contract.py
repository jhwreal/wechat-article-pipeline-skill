#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, sys
from pathlib import Path
from typing import Any, Mapping, Callable

SLOT_KEYS = ('index','name','output','position','role','image_type','target_effect','local_context','source_context','content_focus','visual_distance','composition','emotional_tone','abstraction_level','information_density','visual_type','text_budget','purpose','must_include','quality_gate','variation_note','selection_criteria')

def _safe_output(value: Any) -> str:
    s = str(value or '').strip()
    if not s or s.startswith('/') or s.startswith('\\') or '..' in Path(s).parts:
        raise ValueError(f'unsafe output: {s!r}')
    return s

def normalize_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]:
    version = payload.get('schema_version', 1)
    if version not in (1, 2): raise ValueError(f'unknown schema version: {version}')
    if version == 2:
        out = {k: payload[k] for k in ('kind','schema_version','article','rules','review_defaults') if k in payload}
        out['kind']='wechat-image-jobs'; out['schema_version']=2
        out['article'] = dict(payload.get('article') or {})
        out['rules'] = dict(payload.get('rules') or {})
        out['review_defaults'] = dict(payload.get('review_defaults') or {})
        out['slots'] = [{k:s[k] for k in SLOT_KEYS if k in s} for s in payload.get('slots', [])]
        out['generation_queue'] = [dict(q) for q in payload.get('generation_queue', [])]
        return validate_image_jobs(out)
    raw = payload.get('jobs') or payload.get('slots') or payload.get('image_slots') or (payload.get('image_plan') or {}).get('image_slots') or []
    slots=[]; prompts={}
    queue = payload.get('generation_queue') or []
    qmap={str(q.get('slot') or q.get('name')):q for q in queue}
    for i, item in enumerate(raw):
        d=dict(item)
        # Historical planners sometimes emitted several candidate variants for one
        # slot.  Preserve the first deterministic candidate as the canonical route;
        # downstream consumers must never fan out into duplicate assets.
        variants=d.get('variants') or d.get('candidates') or []
        if isinstance(variants, list) and variants:
            candidate=dict(variants[0]) if isinstance(variants[0], Mapping) else {}
            merged=dict(candidate); merged.update(d); d=merged
        name=str(d.get('name') or d.get('slot') or '').strip()
        output=d.get('output') or d.get('final_output') or (qmap.get(name) or {}).get('output') or f'{name}.png'
        prompt=d.get('generation_prompt') or d.get('prompt') or (qmap.get(name) or {}).get('generation_prompt') or (qmap.get(name) or {}).get('prompt') or (d.get('generation_task') or {}).get('generation_prompt') or (d.get('generation_task') or {}).get('prompt')
        slot={'index': d.get('index',i+1), 'name':name, 'output':_safe_output(output)}
        for k in SLOT_KEYS:
            if k in ('index','name','output'): continue
            if k in d: slot[k]=d[k]
        slots.append(slot)
        if prompt is not None: prompts[name]=prompt
    source_article=payload.get('article') or payload.get('article_meta') or {}
    article={'slug': payload.get('article_slug') or source_article.get('slug'),
             'title': payload.get('article_title') or source_article.get('title'),
             'type': payload.get('article_type') or source_article.get('type'),
             'visual_mode': payload.get('visual_mode') or source_article.get('visual_mode'),
             'visual_intent': payload.get('visual_intent') or source_article.get('visual_intent')}
    article={k:v for k,v in article.items() if v is not None}
    rules=payload.get('rules') or {'version': (payload.get('image_rules') or {}).get('version','1')}
    digest=hashlib.sha256(json.dumps(rules,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    review={'must_avoid': payload.get('must_avoid',[]), 'quality_floor': payload.get('quality_floor',[])}
    return validate_image_jobs({'kind':'wechat-image-jobs','schema_version':2,'article':article,'rules':{'version':rules.get('version'),'sha256':digest},'review_defaults':review,'slots':slots,'generation_queue':[{'slot':s['name'],'output':s['output'],'generation_prompt':prompts.get(s['name'],'')} for s in slots]})

def validate_image_jobs(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get('kind')!='wechat-image-jobs' or payload.get('schema_version')!=2: raise ValueError('invalid image jobs kind/schema')
    slots=[dict(s) for s in payload.get('slots',[])]
    names=[s.get('name') for s in slots]; outputs=[s.get('output') for s in slots]
    if (names and (any(not n for n in names) or len(set(names))!=len(names) or len(set(outputs))!=len(outputs))) or (not names and payload.get('generation_queue')): raise ValueError('slot names and outputs must be unique')
    for o in outputs: _safe_output(o)
    queue=[dict(q) for q in payload.get('generation_queue',[])]
    if any(set(q)!= {'slot','output','generation_prompt'} for q in queue): raise ValueError('queue keys must be exactly slot/output/generation_prompt')
    if {q['slot'] for q in queue} != set(names) or any(q['output'] != slots[names.index(q['slot'])]['output'] for q in queue): raise ValueError('queue/slot mismatch')
    out=dict(payload); out['slots']=slots; out['generation_queue']=queue; return out

def filter_missing_image_jobs(payload: Mapping[str, Any], exists: Callable[[str], bool]) -> dict[str, Any]:
    p=normalize_image_jobs(payload); keep=[s for s in p['slots'] if not exists(s['output'])]; names={s['name'] for s in keep}; p['slots']=keep; p['generation_queue']=[q for q in p['generation_queue'] if q['slot'] in names]; return validate_image_jobs(p) if keep else {**p,'slots':[],'generation_queue':[]}

def slots_by_name(payload): return {s['name']:s for s in normalize_image_jobs(payload)['slots']}
def derive_image_plan(payload):
    p=normalize_image_jobs(payload); return {'article':p['article'],'slots':p['slots']}
def render_image_plan_markdown(payload):
    p=normalize_image_jobs(payload); return '\n'.join(['| name | output | role |','|---|---|---|']+[f"| {s['name']} | {s['output']} | {s.get('role','')} |" for s in p['slots']])

if __name__ == '__main__':
    try: validate_image_jobs(normalize_image_jobs(json.loads(Path(sys.argv[1]).read_text())))
    except Exception as e: raise SystemExit(f'{sys.argv[1]}: {e}')
