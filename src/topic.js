import {esc,route,link,count,level,crumb,title,tag} from './ui.js';
import {getSources} from './data.js';
function studyContent(c) {
  const source = c.source;
  const sources = source.references || [source];
  const citations = sources.map(s => {
    const revisionURL = s.revision?.revid ? `https://en.wikipedia.org/w/index.php?oldid=${encodeURIComponent(s.revision.revid)}` : new URL(s.url).href;
    return `${link(s.title,revisionURL)} · ${esc(s.publisher)} · ${link(s.license,s.license_url)}`;
  }).join('<br>');
  return `<h2>Overview</h2>${c.overview.map(b => `<p class="description">${esc(b.text)}</p>`).join('')}<h2>Key facts</h2><ul class="facts">${c.key_facts.map(b => `<li>${esc(b.text)}</li>`).join('')}</ul><p class="muted">${sources.length > 1 ? 'Sources' : 'Source'}: ${citations}. Adapted summary.</p>`;
}

export function topicHTML(t,params,corpus,subcategories) {
      const s = subcategories.get(params.get('from'));
      const crumbs = [link(t.primary_category,route('category',t.primary_category))];
      if (s && t.subcategory_ids.includes(s.subcategory_id)) crumbs.push(link(s.label,route('subcategory',s.subcategory_id)));
      crumbs.push(`<span aria-current="page">${esc(t.topic)}</span>`);
      const siblings = corpus.topics.filter(x => x.subject_id === t.subject_id && x.study_topic_id !== t.study_topic_id);
      return crumb(crumbs) + title(t.topic) + `<section class="panel"><dl>
        <dt>Primary category</dt><dd>${link(t.primary_category,route('category',t.primary_category))}</dd>
        <dt>Subcategories</dt><dd class="tags">${t.subcategory_ids.map(id => tag(subcategories.get(id))).join('')}</dd>
        <dt>Type</dt><dd>${esc(t.topic_type.replaceAll('_',' '))}</dd>
        ${t.aliases.length ? `<dt>Also known as</dt><dd>${t.aliases.map(esc).join('; ')}</dd>` : ''}
        <dt>School levels</dt><dd>${Object.keys(t.level_occurrence_counts).map(level).map(esc).join(', ')}</dd>
        <dt>Source questions</dt><dd>${count(t.source_question_count)}</dd></dl></section>
        ${t.study_scope ? `<h2>Study scope</h2><p class="scope description">${esc(t.study_scope)}</p>` : ''}
        ${t.study_content ? studyContent(t.study_content) : (t.description ? `<h2>Description</h2><p class="description">${esc(t.description)}</p>` : '')}
        ${siblings.length ? `<h2>Other category pages</h2><div class="tags">${siblings.map(x => link(x.primary_category,route('topic',x.study_topic_id),'tag')).join('')}</div>` : ''}
        <h2>Source questions</h2><button id="load-sources">Show ${count(t.source_question_count)} source question${t.source_question_count === 1 ? '' : 's'}</button><div id="sources" class="sources"></div>`;
}
export async function loadSources(t,button) {
  const container = document.querySelector('#sources');
  button.disabled = true; button.textContent = 'Loading…';
  try {
    const questions = await getSources(t.source_ids);
    if (!container.isConnected) return;
    container.innerHTML = t.source_ids.map(id => {
      const q = questions[id];
      return `<details><summary>${esc(q.source)} · Round ${esc(q.round)} · ${q.question_type === 'bonuses' ? 'Bonus' : 'Tossup'} ${esc(q.number)} <span class="muted">· ${esc(level(q.level))}</span></summary>${q.parts.map(p => `<div class="part">${p.label ? `<strong>${esc(p.label === 'L' ? 'Lead-in' : p.label)}</strong>` : ''}<p>${esc(p.question)}</p>${p.answer ? `<p><strong>Answer:</strong> ${esc(p.answer)}</p>` : ''}</div>`).join('')}</details>`;
    }).join('');
    button.remove();
  } catch (error) {button.disabled=false;button.textContent='Retry source questions';container.textContent=error.message;}
}
