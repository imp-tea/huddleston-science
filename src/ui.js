const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const route = (kind, id, sub = '') => '#' + new URLSearchParams({[kind]: id, ...(sub ? {from:sub} : {})});
const link = (text, href, cls = '') => `<a href="${esc(href)}" class="${cls}">${esc(text)}</a>`;
const sorted = list => [...list].sort((a,b) => (a.topic || a.label || a.primary_category).localeCompare(b.topic || b.label || b.primary_category));
const count = n => n.toLocaleString();
const level = key => ({'high-school':'High school','middle-school':'Middle school'}[key] || key);
const crumb = parts => `<nav class="breadcrumbs" aria-label="Breadcrumb">${[link('Categories','#'),...parts].join('<span aria-hidden="true">/</span>')}</nav>`;
const title = text => `<h1 tabindex="-1">${esc(text)}</h1>`;
const tag = s => link(s.label,route('subcategory',s.subcategory_id),'tag');

export {esc,route,link,sorted,count,level,crumb,title,tag};
