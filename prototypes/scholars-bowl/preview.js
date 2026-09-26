/* Isolated visual prototype. Sample completion data never leaves this page. */
const main = document.querySelector('#main');
const dialog = document.querySelector('#interests-dialog');
const themes = {
  'Arts and Music': ['#c9b877', '#373124', 'music'],
  'Everyday Life and Culture': ['#c4ad8a', '#332e26', 'spark'],
  Geography: ['#b4bc93', '#2e3228', 'globe'],
  Literature: ['#c5acb5', '#342c30', 'book'],
  Mathematics: ['#c3bd91', '#333126', 'orbit'],
  'Popular Media and Entertainment': ['#c8ad96', '#352d27', 'spark'],
  'Religion and Mythology': ['#bdb0c3', '#302c34', 'spark'],
  'Science and Technology': ['#aabcc3', '#293136', 'orbit'],
  'Social Science and Philosophy': ['#bcbd9b', '#303127', 'orbit'],
  'Sports and Games': ['#b0bd9c', '#2d3228', 'spark'],
  'U.S. History': ['#c8a58a', '#362d26', 'column'],
  'World History': ['#c4b080', '#353023', 'column'],
};
let catalog;
let topicsById;
let subsById;
let topicsBySub;
let interests = new Set(['Geography', 'Literature', 'Science and Technology', 'World History']);
let choices = [];
let activeSession = null;
let sampleCompleted = new Set();
let dialogOpener;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}
// Dark accents remain available for progress bars outside the paper cards.
const paperThemes = {
  'Arts and Music': ['#806128', '#eee5cb'],
  'Everyday Life and Culture': ['#805b39', '#eee3d3'],
  Geography: ['#49634c', '#e1e6d6'],
  Literature: ['#77566a', '#ece0e4'],
  Mathematics: ['#69603a', '#e9e4ce'],
  'Popular Media and Entertainment': ['#805d47', '#eee0d5'],
  'Religion and Mythology': ['#6b5b77', '#e8e1ed'],
  'Science and Technology': ['#476779', '#dfe7e9'],
  'Social Science and Philosophy': ['#64683f', '#e5e6d3'],
  'Sports and Games': ['#516d48', '#e1e7d7'],
  'U.S. History': ['#82573c', '#efe0d2'],
  'World History': ['#765e33', '#ece3cb'],
};
function theme(category, surface = 'paper') {
  const palette = surface === 'dark' ? themes : paperThemes;
  const [accent, wash] = palette[category] || palette.Geography;
  return `--accent:${accent};--wash:${wash}`;
}
function svg(kind, className = 'art') {
  const drawings = {
    book: '<path d="M24 40q28-10 56 8v73q-27-18-56-8zM80 48q29-18 56-8v73q-28-5-56 8"/><path d="M33 52q18-4 35 5m-35 7q18-4 35 5m-35 7q18-4 35 5m-35 7q18-4 35 5m25-36q17-9 34-5m-34 17q17-9 34-5m-34 17q17-9 34-5m-34 17q17-9 34-5M17 49v71q34-8 63 9 29-17 63-9V49"/><path d="m105 29 4-12m11 19 11-8M48 28l-8-11"/>',
    progress: '<path d="M24 122h117M35 117V93h22v24m10 0V74h22v43m10 0V51h22v66"/><path d="m28 73 31-20 29 5 40-31m-20 0h20v20"/><circle cx="59" cy="53" r="3"/><circle cx="88" cy="58" r="3"/><path d="m41 32 4-8 4 8 8 4-8 4-4 8-4-8-8-4z"/>',
    globe: '<circle cx="80" cy="70" r="44"/><ellipse cx="80" cy="70" rx="19" ry="44"/><path d="M36 70h88M42 49q38 15 76 0M42 91q38-15 76 0M80 26v88m-48-83q-38 55 16 92 49 30 83-23M48 123l-8 15m8-15 8 15M29 138h37"/><path d="m129 24 3-8 3 8 8 3-8 3-3 8-3-8-8-3z"/>',
    orbit: '<ellipse cx="80" cy="77" rx="59" ry="23"/><ellipse cx="80" cy="77" rx="59" ry="23" transform="rotate(60 80 77)"/><ellipse cx="80" cy="77" rx="59" ry="23" transform="rotate(120 80 77)"/><circle cx="80" cy="77" r="7"/><circle cx="130" cy="65" r="4"/>',
    music: '<path d="M24 49h112M24 64h112M24 79h112M24 94h112M24 109h112M65 99V33l48-9v63M65 48l48-9"/><ellipse cx="54" cy="103" rx="11" ry="8"/><ellipse cx="102" cy="91" rx="11" ry="8"/>',
    column: '<path d="m22 48 58-29 58 29zM29 56h102M29 118h102M22 128h116M41 62v49m10-49v49m24-49v49m10-49v49m24-49v49m10-49v49"/><path d="M36 57h20m14 0h20m14 0h20"/>',
    spark: '<path d="m80 21 12 39 39-17-25 34 33 24-40-4-8 40-16-38-36 19 21-35-33-24 41 4z"/><circle cx="80" cy="80" r="10"/>',
  };
  return `<svg class="${className}" viewBox="0 0 160 155" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${drawings[kind] || drawings.spark}</svg>`;
}
function shuffled(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}
function completion(topics) {
  const done = topics.filter(topic => sampleCompleted.has(topic.id)).length;
  return {done, total: topics.length, percent: topics.length ? Math.floor(done / topics.length * 100) : 0};
}
function crumbs(parts) {
  return `<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="#home">Scholars Bowl</a>${parts.map(([label, href]) => `<span class="crumb-separator" aria-hidden="true">/</span>${href ? `<a href="${esc(href)}">${esc(label)}</a>` : `<span aria-current="page">${esc(label)}</span>`}`).join('')}</nav>`;
}
function heading(title, subtitle = '') {
  return `<div class="page-heading"><h1>${title}</h1>${subtitle ? `<p>${subtitle}</p>` : ''}</div>`;
}
function home() {
  return `<h1 class="sr-only">Scholars Bowl</h1><div class="landing-grid">
    ${[['study', 'Study', 'Learn a few random topics and take a quiz!', 'book'], ['progress', 'Progress', 'See your learning progress!', 'progress'], ['explore', 'Explore', 'Freely explore the full data set!', 'globe']].map(([route, title, subtitle, icon]) => `<a class="destination destination-${route}" href="#${route}">${svg(icon)}<h2>${title}</h2><p>${subtitle}</p><span class="circle-arrow" aria-hidden="true">↗</span></a>`).join('')}
    </div>`;
}
function reshuffle() {
  const eligible = catalog.subcategories.filter(sub => interests.has(sub.primary_category) && topicsBySub.get(sub.subcategory_id)?.some(topic => !sampleCompleted.has(topic.id)));
  const old = new Set(choices.map(sub => sub.subcategory_id));
  choices = [...shuffled(eligible.filter(sub => !old.has(sub.subcategory_id))), ...shuffled(eligible.filter(sub => old.has(sub.subcategory_id)))].slice(0, 10);
}
function studyCards() {
  return choices.map((sub, index) => {
    const progress = completion(topicsBySub.get(sub.subcategory_id));
    const remaining = progress.total - progress.done;
    const shortLabel = remaining < 5 ? `Short session · ${remaining} ${remaining === 1 ? 'topic' : 'topics'}` : '';
    return `<button type="button" class="study-card" data-action="choose" data-id="${esc(sub.subcategory_id)}" style="${theme(sub.primary_category)};--fill:${progress.percent}%;--order:${index}" aria-label="${esc(sub.label)} (${progress.percent}% complete)${shortLabel ? ` · ${shortLabel}` : ''}"><span class="card-fill"></span><span class="category-label">${esc(sub.primary_category)}</span><h2>${esc(sub.label)}</h2>${shortLabel ? `<span class="short-session-label">${shortLabel}</span>` : ''}<span class="card-bottom"><span>${progress.percent}% complete</span><span aria-hidden="true">↗</span></span>${svg(themes[sub.primary_category]?.[2], 'motif')}</button>`;
  }).join('');
}
function study() {
  if (activeSession) {
    return `${crumbs([['Study']])}<section class="complete-panel"><h1>Unfinished session</h1><p>${esc(activeSession.sub.label)} · Topic ${activeSession.position + 1} of ${activeSession.topics.length}<br>Starting a new session clears only this unfinished session’s progress. Previously completed topics stay completed.</p><div class="actions"><a class="primary-button" href="#read">Resume Previous Session →</a><button class="secondary-button" data-action="new-session">Start New Session</button></div></section>`;
  }
  if (!choices.length) reshuffle();
  return `${crumbs([['Study']])}${heading('What do you want to learn about today?')}
    <div class="section-bar"><span class="eyebrow">${interests.size} SELECTED CATEGORIES</span><button class="text-button" data-action="interests">Edit interests ↗</button></div>
    <div class="study-grid" id="study-grid">${studyCards() || '<p class="notice">All topics in your selected categories are complete. Edit interests to choose more categories.</p>'}</div>
    <div class="reshuffle-row"><button class="reshuffle" data-action="reshuffle"><span class="reshuffle-icon" aria-hidden="true">⤨</span> Reshuffle</button></div><p class="picker-footnote">Card fills show sample topic completion in this design preview.</p>`;
}
function readingCard(topic, number = null) {
  const overview = topic.overview || [];
  const lede = overview.length ? overview[0].text : topic.description;
  const references = (topic.references || []).filter(ref => /^https?:\/\//i.test(ref.url || ''));
  return `<article class="reading-card" style="${theme(topic.category)}"><span class="category-label">${esc(topic.category)}</span>${number ? `<span class="chapter" aria-hidden="true">${String(number).padStart(2, '0')}</span>` : ''}<h1>${esc(topic.title)}</h1><p class="lede">${esc(lede)}</p><div class="overview">${overview.slice(1).map(block => `<p>${esc(block.text)}</p>`).join('')}</div>${topic.facts.length ? `<aside class="fact-box"><p class="eyebrow">KEY FACTS</p><ul>${topic.facts.map(fact => `<li>${esc(fact.text)}</li>`).join('')}</ul></aside>` : ''}${references.length ? `<details class="reading-sources"><summary>Reading sources & attribution</summary>${references.map(ref => `<a href="${esc(ref.url)}" target="_blank" rel="noopener noreferrer">${esc(ref.title || ref.publisher || 'Reference')} ↗</a>`).join('')}<a href="attribution.html" target="_blank" rel="noopener">Content credits & licenses ↗</a></details>` : ''}</article>`;
}
function reader() {
  if (!activeSession) return study();
  const {topics, position, sub} = activeSession;
  const topic = topics[position];
  return `${crumbs([['Study', '#study'], [sub.label]])}<div class="reader-shell" style="${theme(topic.category, 'dark')}"><div class="reading-progress"><div class="reading-progress-label"><strong>LEARNING MODE</strong><span>Topic ${position + 1} of ${topics.length}</span></div><div class="segment-bar" role="progressbar" aria-label="Reading position" aria-valuemin="0" aria-valuemax="${topics.length}" aria-valuenow="${position + 1}">${topics.map((_, index) => `<span class="${index <= position ? 'filled' : ''}"></span>`).join('')}</div></div>${readingCard(topic, position + 1)}<div class="reader-controls"><span>${esc(sub.label)}${topics.length < 5 ? ' · Short session' : ''}</span><div><button class="secondary-button" data-action="previous" ${position === 0 ? 'disabled' : ''}>← Back</button><button class="primary-button" data-action="next">${position === topics.length - 1 ? 'Finish reading' : 'Next topic'} <span aria-hidden="true">→</span></button></div></div></div>`;
}
function ready() {
  if (!activeSession) return study();
  return `${crumbs([['Study', '#study'], ['Reading complete']])}<section class="complete-panel"><h1>Reading complete</h1><p>You’ve read ${activeSession.topics.length} topics in ${esc(activeSession.sub.label)}.</p><p>This is the end of the reading preview. The next pass adds the typed quiz, targeted review, and saved completion.</p><div class="actions"><a class="secondary-button" href="#read">Revisit the reading</a><button class="primary-button" data-action="new-session">Try another subject →</button></div></section>`;
}
function categoryCard(category) {
  const topics = catalog.topics.filter(topic => topic.category === category);
  const subs = catalog.subcategories.filter(sub => sub.primary_category === category);
  return `<a class="category-card" href="#explore/${encodeURIComponent(category)}" style="${theme(category)}"><h2>${esc(category)}</h2><p>${subs.length} subjects · ${topics.length.toLocaleString()} topics</p>${svg(themes[category]?.[2], 'motif')}</a>`;
}
function topicLinks(topics, category, subId) {
  return `<ul class="topic-list">${topics.map(topic => `<li><a href="#topic/${encodeURIComponent(topic.id)}/${encodeURIComponent(category || topic.category)}/${encodeURIComponent(subId || topic.subcategories[0])}"><span>${esc(topic.title)}</span><span class="topic-arrow" aria-hidden="true">↗</span></a></li>`).join('')}</ul>`;
}
function explore(category, subId) {
  if (!category) return `${crumbs([['Explore']])}${heading('Explore')}<label class="search-label" for="topic-search">Find a topic</label><input class="search" id="topic-search" type="search" placeholder="Search topics…" autocomplete="off"><div id="explore-results"><div class="category-grid">${catalog.categories.map(categoryCard).join('')}</div></div>`;
  if (!catalog.categories.includes(category)) return notFound();
  if (subId) {
    const sub = subsById.get(subId);
    if (!sub || sub.primary_category !== category) return notFound();
    const topics = [...(topicsBySub.get(subId) || [])].sort((a, b) => a.title.localeCompare(b.title));
    return `${crumbs([['Explore', '#explore'], [category, `#explore/${encodeURIComponent(category)}`], [sub.label]])}${heading(esc(sub.label), `${topics.length} topics`)}${topicLinks(topics, category, subId)}`;
  }
  const subs = catalog.subcategories.filter(sub => sub.primary_category === category);
  return `${crumbs([['Explore', '#explore'], [category]])}${heading(esc(category))}<div class="category-grid">${subs.map(sub => `<a class="category-card" href="#explore/${encodeURIComponent(category)}/${esc(sub.subcategory_id)}" style="${theme(category)}"><h2>${esc(sub.label)}</h2><p>${topicsBySub.get(sub.subcategory_id)?.length || 0} topics <span aria-hidden="true">↗</span></p>${svg(themes[category]?.[2], 'motif')}</a>`).join('')}</div>`;
}
function exploreTopic(id, category, subId) {
  const topic = topicsById.get(id);
  if (!topic) return notFound();
  const requestedSub = subsById.get(subId);
  const sub = requestedSub && topic.subcategories.includes(subId) ? requestedSub : subsById.get(topic.subcategories[0]);
  category = sub?.primary_category || topic.category;
  return `${crumbs([['Explore', '#explore'], [category, `#explore/${encodeURIComponent(category)}`], ...(sub ? [[sub.label, `#explore/${encodeURIComponent(category)}/${sub.subcategory_id}`]] : []), [topic.title]])}<div class="reader-shell">${readingCard(topic)}</div>`;
}
function activitySquares() {
  // Use Chicago's calendar date even when the preview runs in another timezone.
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: 'America/Chicago', year: 'numeric', month: 'numeric', day: 'numeric'}).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  const today = new Date(Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day)));
  const mondayOffset = (today.getUTCDay() + 6) % 7;
  const start = new Date(today);
  start.setUTCDate(today.getUTCDate() - mondayOffset - 28);
  return Array.from({length: 35}, (_, i) => {
    const date = new Date(start);
    date.setUTCDate(start.getUTCDate() + i);
    const future = date > today;
    const level = future ? 0 : [0, 1, 0, 2, 3, 1, 0, 1, 2, 0, 2][i % 11];
    const label = `${date.toLocaleDateString(undefined, {timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'})}: ${future ? 'upcoming' : `${level} sample activities`}`;
    return `<span class="activity-square ${future ? 'future' : `level-${level}`}" role="img" aria-label="${esc(label)}" title="${esc(label)}"></span>`;
  }).join('');
}
function progress() {
  return `${crumbs([['Progress']])}${heading('Progress')}<div class="progress-overview"><section class="progress-panel"><p class="eyebrow">WEEKLY GOAL</p><div class="weekly-number">3 <small>of 5 sessions · 60%</small></div><div class="progress-track" role="progressbar" aria-label="Sample weekly progress" aria-valuemin="0" aria-valuemax="5" aria-valuenow="3" style="--fill:60%"><span></span></div><p class="muted">2 sessions remaining. Monday–Sunday · Central time.</p></section><section class="progress-panel"><p class="eyebrow">ACTIVITY</p><div class="activity-row"><div class="activity-grid">${activitySquares()}</div><p>Your last five weeks of reading and practice.</p></div><div class="activity-legend">Less <i class="activity-square"></i><i class="activity-square level-1"></i><i class="activity-square level-2"></i><i class="activity-square level-3"></i> More<span> · Sample activity</span></div></section></div><div class="section-bar"><span class="eyebrow">CATEGORY PROGRESS</span><span class="muted" style="font-size:.72rem">Sample progress for this preview</span></div>${catalog.categories.map(category => {
    const stats = completion(catalog.topics.filter(topic => topic.category === category));
    const subs = catalog.subcategories.filter(sub => sub.primary_category === category);
    return `<details class="category-progress" style="${theme(category, 'dark')}"><summary><h2>${esc(category)}</h2><div class="progress-track" style="--fill:${stats.percent}%"><span></span></div><span class="percentage">${stats.percent}%</span><span class="expand-symbol" aria-hidden="true">+</span></summary><p class="muted" style="font-size:.75rem;margin-top:13px">${stats.done} of ${stats.total} topics completed</p><div class="sub-progress">${subs.map(sub => {
      const subStats = completion(topicsBySub.get(sub.subcategory_id) || []);
      return `<div><a href="#explore/${encodeURIComponent(category)}/${sub.subcategory_id}">${esc(sub.label)}</a><span>${subStats.done}/${subStats.total} · ${subStats.percent}%</span></div>`;
    }).join('')}</div></details>`;
  }).join('')}`;
}
function notFound() {
  return `${crumbs([['Not found']])}<section class="complete-panel"><h1>Page not found</h1><p>That page isn’t in this preview.</p><a class="primary-button" href="#home">Back to Scholars Bowl</a></section>`;
}
function render({focus = true} = {}) {
  let route;
  try { route = (location.hash.slice(1) || 'home').split('/').map(decodeURIComponent); }
  catch { route = ['not-found']; }
  const [page, ...args] = route;
  const screens = {home, study, read: reader, ready, progress, explore, topic: exploreTopic};
  main.innerHTML = (screens[page] || notFound)(...args);
  document.title = `${({home: 'Scholars Bowl', study: 'Study', read: 'Learning mode', ready: 'Reading complete', progress: 'Your progress', explore: 'Explore the library', topic: 'Explore a topic'})[page] || 'Scholars Bowl'} · Huddleston Science`;
  if (focus) {
    main.focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: 'instant'});
  }
}
function openInterests(opener) {
  dialogOpener = opener;
  dialog.innerHTML = `<form id="interests-form"><div class="dialog-top"><div><h2 id="interests-title">What interests you?</h2></div><button type="button" class="close-button" data-action="close-interests" aria-label="Close interests">×</button></div><p class="dialog-description">Select at least one category for Study. You can edit these later.</p><button type="button" class="text-button" data-action="select-all">Select all categories</button><div class="interest-grid">${catalog.categories.map(category => `<label class="interest-option" style="${theme(category)}"><input type="checkbox" name="category" value="${esc(category)}" ${interests.has(category) ? 'checked' : ''}>${esc(category)}</label>`).join('')}</div><div class="dialog-footer"><p id="interest-count">${interests.size} categories selected</p><button class="primary-button" id="save-interests" type="submit">Save interests →</button></div></form>`;
  dialog.showModal();
}
function updateInterestCount() {
  const count = dialog.querySelectorAll('input:checked').length;
  document.querySelector('#interest-count').textContent = count ? `${count} categories selected` : 'Choose at least one category.';
  document.querySelector('#save-interests').disabled = count === 0;
}
dialog.addEventListener('close', () => {
  // Saving may replace the picker, so its original Edit interests button is gone.
  const opener = dialogOpener?.isConnected ? dialogOpener : main.querySelector('[data-action="interests"]');
  opener?.focus();
});
dialog.addEventListener('change', updateInterestCount);
dialog.addEventListener('submit', event => {
  event.preventDefault();
  const selected = new FormData(event.target).getAll('category');
  if (!selected.length) return;
  interests = new Set(selected);
  choices = [];
  dialog.close();
  if (location.hash === '#study' && !activeSession) render();
  document.querySelector('#announcement').textContent = 'Interests updated for this preview. Your next choices will use these categories.';
});
document.addEventListener('click', event => {
  const control = event.target.closest('[data-action]');
  if (!control || !catalog) return;
  const action = control.dataset.action;
  if (action === 'interests') openInterests(control);
  if (action === 'close-interests') dialog.close();
  if (action === 'select-all') { dialog.querySelectorAll('input').forEach(input => { input.checked = true; }); updateInterestCount(); }
  if (action === 'reshuffle') {
    reshuffle();
    document.querySelector('#study-grid').innerHTML = studyCards();
    document.querySelector('#announcement').textContent = `${choices.length} subjects available from your selected interests.`;
  }
  if (action === 'choose') {
    const sub = subsById.get(control.dataset.id);
    const topics = shuffled(topicsBySub.get(sub.subcategory_id).filter(topic => !sampleCompleted.has(topic.id))).slice(0, 5);
    if (!topics.length) return;
    activeSession = {sub, topics, position: 0};
    location.hash = 'read';
  }
  if (action === 'new-session') {
    activeSession = null;
    choices = [];
    if (location.hash !== '#study') location.hash = 'study';
    else render();
  }
  if (action === 'previous' && activeSession?.position > 0) { activeSession.position--; render(); }
  if (action === 'next' && activeSession) {
    if (activeSession.position === activeSession.topics.length - 1) location.hash = 'ready';
    else { activeSession.position++; render(); }
  }
});
document.addEventListener('input', event => {
  if (event.target.id !== 'topic-search') return;
  const query = event.target.value.trim().toLocaleLowerCase();
  const results = document.querySelector('#explore-results');
  if (!query) { results.innerHTML = `<div class="category-grid">${catalog.categories.map(categoryCard).join('')}</div>`; return; }
  const found = catalog.topics.filter(topic => topic.title.toLocaleLowerCase().includes(query));
  results.innerHTML = `<p class="muted" style="margin-bottom:15px;font-size:.8rem">${found.length} topics found${found.length > 100 ? ' · Showing the first 100; refine your search for more' : ''}</p>${topicLinks(found.slice(0, 100))}`;
});
window.addEventListener('hashchange', () => { if (catalog) render(); });

async function init() {
  try {
    const response = await fetch('catalog.json');
    if (!response.ok) throw new Error('Catalog unavailable');
    catalog = await response.json();
    topicsById = new Map(catalog.topics.map(topic => [topic.id, topic]));
    subsById = new Map(catalog.subcategories.map(sub => [sub.subcategory_id, sub]));
    topicsBySub = new Map(catalog.subcategories.map(sub => [sub.subcategory_id, []]));
    catalog.topics.forEach(topic => topic.subcategories.forEach(id => topicsBySub.get(id)?.push(topic)));
    // Stable sample completions, shared across every subcategory membership.
    catalog.topics.forEach((topic, index) => { if (index % 7 === 0 || index % 19 === 0) sampleCompleted.add(topic.id); });
    render({focus: false});
  } catch (error) {
    main.innerHTML = '<div class="loading"><h1>The library couldn’t open.</h1><p>Run the preview server and refresh this page.</p><a href="/">Try again →</a></div>';
    console.error(error);
  }
}
init();
