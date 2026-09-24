// Optional local benchmark against the authoritative corpus (no sibling repo).
import fs from 'node:fs';
import Quiz from '../static/typed-matching.js';
const topics = new Map(JSON.parse(fs.readFileSync(new URL('../data/topics.json', import.meta.url))).map(t => [t.study_topic_id, t.primary_category]));
const banks = new Map();
const root = new URL('../data/practice/', import.meta.url);
for (const file of fs.readdirSync(root).filter(f => f.endsWith('.json')).sort()) {
  for (const q of JSON.parse(fs.readFileSync(new URL(file, root)))) {
    const category = topics.get(q.study_topic_id);
    if (!banks.has(category)) banks.set(category, new Map());
    const bank = banks.get(category);
    for (const a of [q.correct_answer, ...q.distractors]) if (!bank.has(Quiz.answerKey(a))) bank.set(Quiz.answerKey(a), a.trim());
  }
}
const [category, bank] = [...banks.entries()].sort((a,b) => b[1].size-a[1].size)[0];
const indexStart = performance.now();
const index = Quiz.answerIndex([...bank.values()]);
const indexMs = performance.now()-indexStart;
const prepStart = performance.now();
for (let i=0; i<100; i++) Quiz.questionBank(index, "Saturn's rings");
const prepareMs = (performance.now()-prepStart)/100;
const durations = ['ein','einstien','photosyntheis','thermodynamcis','mitochondria','asdfghjkl','electromagnetic induction'].map(q => {
  const start = performance.now(); Quiz.suggestions(index,q); return performance.now()-start;
});
console.log(JSON.stringify({category, answers:bank.size, indexMs, prepareMs, minSearchMs:Math.min(...durations), maxSearchMs:Math.max(...durations)},null,2));
