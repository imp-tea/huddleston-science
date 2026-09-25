"""Build an offline review page from immutable pilot outputs and editorial notes."""
import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path

from typed_question_pilot import DEFAULT_RUN, read


def render(run):
    manifest, summary, audit = [read(run / f) for f in ('manifest.json', 'summary.json', 'editorial-review.json')]
    notes = {q['question_id']: q for q in audit['questions']}
    version = manifest.get('version', 'v1')
    model = manifest['model']
    cards = []
    categories = set()
    markdown = ['# Typed-question pilot: original outputs', '',
                f"{summary['ready_questions']} unedited {model} questions ({version}). Editorial notes are separate from the original output.", '',
                '“No blocking issue noted” is an editorial screen, not factual certification.', '']
    for i, entry in enumerate(manifest['topics'], 1):
        c = entry['context']; categories.add(c['category'])
        record = read(run / 'responses' / (c['study_topic_id'] + '.json'))
        markdown += [f"## {i}. {c['topic']} — {c['category']}", '',
                     f"{c['source_question_count']} source(s); {c['requested_question_count']} requested questions.", '']
        for slot, q in enumerate(record['result']['questions'], 1):
            qid = f"typed-pilot-{c['study_topic_id']}-{q.get('slot', slot)}"; note = notes[qid]
            finding = ''.join('<li><strong>' + escape(f['category'].replace('_', ' ')) + ':</strong> ' + escape(f['note']) + '</li>' for f in note['findings'])
            canonical = q['answer'] if version in ('v4', 'v5') else q['canonical_answer']
            answer = '<p class="answer">' + escape(canonical) + '</p>'
            for field, label in [('accepted_answers', 'Also accept'), ('prompt_answers', 'Prompt'), ('rejected_answers', 'Reject')]:
                if field in q:
                    answer += '<p><b>' + label + ':</b> ' + escape('; '.join(q[field]) or '—') + '</p>'
            if 'explanation' in q:
                answer += '<p>' + escape(q['explanation']) + '</p>'
            evidence = []
            for ev in q.get('evidence', []):
                blocks = []
                for eid in ev['evidence_ids']:
                    text = c['evidence_map'][eid]
                    if isinstance(text, dict):
                        text = text['question'] + '\nANSWER: ' + text['answer']
                    blocks.append('<p><code>' + escape(eid) + '</code></p><blockquote>' + escape(text) + '</blockquote>')
                evidence.append('<p><b>' + escape(ev['claim']) + '</b></p>' + ''.join(blocks))
            context = ((run / 'supplied-context' / (c['study_topic_id'] + '.txt')).read_text()
                       if version == 'v5' else json.dumps(c, ensure_ascii=False, indent=2))
            badge = 'Needs attention' if note['screen'] == 'needs_attention' else 'No blocking issue noted'
            evidence_html = '<details><summary>Evidence used by Luna</summary>' + ''.join(evidence) + '</details>' if version not in ('v4', 'v5') else ''
            answer_label = 'Answer' if version in ('v4', 'v5') else 'Answer &amp; explanation'
            difficulty = ' · ' + escape(q['difficulty']) if 'difficulty' in q else ''
            card = f'''<article data-category="{escape(c['category'], quote=True)}" data-status="{note['screen']}" id="q-{note['ref']}">
<div class="meta">{note['ref']} · {escape(c['category'])} · {c['source_question_count']} source(s){difficulty}</div>
<div class="topic">Topic: {escape(c['topic'])}</div><p class="question">{escape(q['question'])}</p>
<details class="answers"><summary>{answer_label}</summary>{answer}</details>
<div class="review"><span class="badge {note['screen']}">{badge}</span>{'<ul>' + finding + '</ul>' if finding else ''}</div>
{evidence_html}
<details><summary>Complete supplied topic context</summary><pre>{escape(context)}</pre></details></article>'''
            cards.append(card)
            markdown += [f"### {note['ref']}", '', q['question'], '', '**Answer:** ' + canonical, '']
            if version not in ('v4', 'v5'):
                markdown += ['**Also accept:** ' + ('; '.join(q['accepted_answers']) or '—'), '',
                             '**Prompt:** ' + ('; '.join(q['prompt_answers']) or '—'), '', q['explanation'], '']
            markdown += ['**Editorial screen:** ' + badge, '']
            markdown += ['- ' + f['note'] for f in note['findings']] + ['']
    options = ''.join('<option>' + escape(c) + '</option>' for c in sorted(categories))
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Typed question pilot __VERSION__ · __READY__ drafts</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#202d2b;font:16px/1.65 system-ui,sans-serif}
header,main{max-width:1040px;margin:auto;padding:28px}header{padding-top:48px}h1{font-size:36px;line-height:1.15;margin:12px 0}.eyebrow{letter-spacing:.12em;text-transform:uppercase;font-size:12px;font-weight:700;color:#557466}
.stats{display:flex;gap:28px;flex-wrap:wrap;margin:24px 0}.stats b{display:block;font-size:28px}.muted,.meta{color:#66716c;font-size:13px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:end;padding:18px;background:white;border:1px solid #d8ddd6;border-radius:12px}
label{display:flex;flex-direction:column;font-size:13px;gap:4px}input,select,button{font:inherit;padding:10px;border:1px solid #aab9ae;border-radius:6px;background:white;color:inherit}input{max-width:100%}button{cursor:pointer}main{padding-top:0}article{background:white;border:1px solid #d8ddd6;border-radius:12px;padding:26px;margin:18px 0}article[hidden]{display:none}.topic{font-size:13px;color:#527064}.question{font-size:21px;line-height:1.55}.answer{font-size:21px;font-weight:700;color:#22583e}summary{cursor:pointer;font-weight:600;margin:8px 0}details{padding:5px 0}details p{margin:10px 0}.review{margin:16px 0;padding:15px;background:#f8f8f5;border-radius:8px}.badge{display:inline-block;font-size:12px;font-weight:700;padding:3px 9px;border-radius:20px;background:#e5eee7}.needs_attention{background:#fff0d8;color:#794b10}li{margin:7px 0}blockquote{margin:12px 0;padding:12px 18px;border-left:3px solid #b6c7b9;background:#f5f7f3;font-size:14px;white-space:pre-wrap}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere;font-size:12px}.hide-topics .topic{display:none}@media(max-width:600px){header,main{padding:20px}h1{font-size:28px}article{padding:18px}.question{font-size:19px}}
</style><header><div class="eyebrow">Huddleston Science · Research pilot __VERSION__ · September 25, 2026</div>
<h1>New questions, designed for typed answers</h1><p>Original, unedited __MODEL__ outputs with a separate editorial screen. Existing multiple-choice questions and the live application were not changed.</p>
<div class="stats"><div><b>__TOPICS__</b>topics · __CATEGORIES__ categories</div><div><b>__READY__</b>questions generated</div><div><b>__COST__</b>estimated API cost</div><div><b>__FLAGGED__</b>questions flagged for attention</div></div>
<p class="muted">__SCOPE__</p>
<div class="toolbar"><label>Search<input id="search" type="search" placeholder="Topic, question, answer…"></label><label>Category<select id="category"><option value="">All categories</option>''' + options + '''</select></label>
<label>Editorial screen<select id="status"><option value="">All questions</option><option value="needs_attention">Needs attention</option><option value="no_blocking_issue_noted">No blocking issue noted</option></select></label>
<button id="answers" type="button">Show all answers</button><button id="topics" type="button">Hide topic labels</button></div><p class="muted" id="count" aria-live="polite">__SLOTS__ slots shown</p></header><main>''' + ''.join(cards) + '''</main><script>
const cards=[...document.querySelectorAll('article')],search=document.querySelector('#search'),category=document.querySelector('#category'),status=document.querySelector('#status');
function filter(){let n=0;for(const c of cards){c.hidden=!!((category.value&&c.dataset.category!==category.value)||(status.value&&c.dataset.status!==status.value)||(search.value&&!c.textContent.toLowerCase().includes(search.value.toLowerCase())));if(!c.hidden)n++}document.querySelector('#count').textContent=n+' questions shown'}
for(const e of [search,category,status])e.addEventListener('input',filter);
let show=false;document.querySelector('#answers').onclick=e=>{show=!show;document.querySelectorAll('.answers').forEach(d=>d.open=show);e.target.textContent=show?'Hide all answers':'Show all answers'};
document.querySelector('#topics').onclick=e=>{const hidden=document.body.classList.toggle('hide-topics');e.target.textContent=hidden?'Show topic labels':'Hide topic labels'};
</script></html>'''
    replacements = {'__MODEL__': model, '__VERSION__': version, '__READY__': summary['ready_questions'],
                    '__TOPICS__': len(manifest['topics']), '__CATEGORIES__': len(categories),
                    '__COST__': f"${summary['totals']['estimated_usd']:.4f}",
                    '__FLAGGED__': audit['counts']['needs_attention'], '__SLOTS__': len(cards),
                    '__SCOPE__': audit['scope']}
    for token, value in replacements.items():
        html = html.replace(token, escape(str(value)))
    (run / 'review.html').write_text(html)
    (run / 'questions.md').write_text('\n'.join(markdown) + '\n')
    return {'html': str(run / 'review.html'), 'questions': len(cards)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    print(json.dumps(render(parser.parse_args().run_dir), indent=2))
