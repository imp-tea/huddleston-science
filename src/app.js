import {esc,route,link,sorted,count,crumb,title} from './ui.js';
import {loadCorpus,getTopic} from './data.js';
import {topicHTML,loadSources} from './topic.js';
import {startQuiz,closeQuiz} from './quiz-dialog.js';
const main = document.querySelector('#main');
let corpus, topics, subcategories, renderToken = 0;
async function render(focus = true) {
  const token = ++renderToken;
  closeQuiz();
  const params = new URLSearchParams(location.hash.slice(1));
  const tid = corpus.redirects[params.get('topic')] || params.get('topic'), sid = params.get('subcategory'), category = params.get('category');
  let heading = 'Categories';
  let quizTopics = null;
  try {
    if (params.has('pilot') || params.has('content')) {
      heading = 'Study pages';
      const list = sorted(corpus.topics.filter(t => t.has_content));
      main.innerHTML = crumb([`<span aria-current="page">${esc(heading)}</span>`]) + title(heading) + `<p class="muted">${list.length} topic pages</p><ul class="topic-list">${list.map(t => `<li><a href="${esc(route('topic',t.study_topic_id))}"><span>${esc(t.topic)}</span><span class="muted">${esc(t.primary_category)}</span></a></li>`).join('')}</ul>`;
    } else if (tid) {
      if (!topics.has(tid)) throw new Error('Topic not found');
      main.innerHTML = '<p role="status">Loading topic…</p>';
      const t = await getTopic(tid);
      if (token !== renderToken) return;
      heading = t.topic;
      main.innerHTML = topicHTML(t,params,corpus,subcategories);
      document.querySelector('#load-sources').addEventListener('click', event => loadSources(t,event.currentTarget));
    } else if (sid) {
      const s = subcategories.get(sid); if (!s) throw new Error('Subcategory not found');
      heading = s.label;
      const list = sorted(corpus.topics.filter(t => t.subcategory_ids.includes(sid)));
      quizTopics = list;
      main.innerHTML = crumb([link(s.primary_category,route('category',s.primary_category)),`<span aria-current="page">${esc(s.label)}</span>`]) + title(s.label) + `<p class="description">${esc(s.definition)}</p><p class="muted">${count(list.length)} topics</p><ul class="topic-list">${list.map(t => `<li>${link(t.topic,route('topic',t.study_topic_id,sid))}</li>`).join('')}</ul>`;
    } else if (category) {
      if (!corpus.categories.some(c => c.primary_category === category)) throw new Error('Category not found');
      heading = category;
      quizTopics = corpus.topics.filter(t => t.primary_category === category);
      const list = sorted(corpus.subcategories.filter(s => s.primary_category === category));
      main.innerHTML = crumb([`<span aria-current="page">${esc(category)}</span>`]) + title(category) + `<p class="muted">${list.length} subcategories · ${count(corpus.topics.filter(t => t.primary_category === category).length)} topics</p><div class="grid">${list.map(s => `<a class="card" href="${esc(route('subcategory',s.subcategory_id))}"><strong>${esc(s.label)}</strong><span class="muted">${count(s.topic_count)} topics</span></a>`).join('')}</div>`;
    } else {
      quizTopics = corpus.topics;
      main.innerHTML = title('Categories') + `<p class="muted">12 categories · ${count(corpus.subcategories.length)} subcategories · ${count(corpus.topics.length)} topics</p><div class="grid">${corpus.categories.map(c => `<a class="card" href="${esc(route('category',c.primary_category))}"><strong>${esc(c.primary_category)}</strong><span class="muted">${c.subcategory_count} subcategories · ${count(c.current_study_topic_count)} topics</span></a>`).join('')}</div>`;
    }
  } catch (error) {if (token !== renderToken) return; quizTopics = null; main.innerHTML = crumb([]) + title(error.message) + '<p><a href="">Reload</a></p>';}
  if (quizTopics) {
    const h1 = main.querySelector('h1');
    const row = document.createElement('div'); row.className = 'page-heading';
    h1.before(row); row.append(h1);
    const button = document.createElement('button'); button.textContent = 'Quiz Me!';
    row.append(button);
    button.addEventListener('click', () => startQuiz(heading, new Set(quizTopics.map(t => t.study_topic_id))));
  }
  document.title = heading + ' · Quiz bowl topics';
  if (focus) {main.querySelector('h1').focus({preventScroll:true});window.scrollTo(0,0);}
}
loadCorpus().then(data => {
  corpus = data; topics = new Map(data.topics.map(t => [t.study_topic_id,t]));subcategories = new Map(data.subcategories.map(s => [s.subcategory_id,{...s,topic_count:0}]));
  for (const t of data.topics) for (const id of t.subcategory_ids) subcategories.get(id).topic_count++;
  corpus.subcategories = [...subcategories.values()];
  if (data.topics.some(t => t.has_content)) document.querySelector('header').insertAdjacentHTML('beforeend', '<a class="pilot-link" href="#content=1">Study pages</a>');
  render(false);window.addEventListener('hashchange',() => render());
}).catch(error => {main.innerHTML = title('Unable to load corpus') + `<p>${esc(error.message)}</p><a href="">Reload</a>`;});
