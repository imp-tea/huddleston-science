import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import Quiz from '../static/typed-matching.js';
const fixtures = JSON.parse(fs.readFileSync(new URL('./fixtures/typed-answers.json', import.meta.url)));
test('shared matching and grading fixtures', () => {
  for (const f of fixtures.suggestions) assert.deepEqual(Quiz.suggestions(Quiz.answerIndex(f.bank), f.query).map(r => r.text), f.expected);
  for (const [given, correct, expected] of fixtures.grades) assert.equal(Quiz.grade(given, correct), expected, `${given} / ${correct}`);
  for (const [correct, other] of fixtures.distinct) assert.equal(Quiz.questionBank(Quiz.answerIndex([correct, other]), correct).suppressedAnswers.size, 0);
  for (const [correct, other] of fixtures.variants) assert.equal(Quiz.questionBank(Quiz.answerIndex([correct, other]), correct).suppressedAnswers.size, 1);
});
test('wording search maps to exact display without mutating the bank', () => {
  const original = Quiz.answerIndex(fixtures.saturn), before = JSON.stringify(original);
  const bank = Quiz.questionBank(original, "Saturn's rings");
  for (const q of ['rings of', 'rings of saturn', 'the rings', 'rigns of saturn']) {
    assert.equal(Quiz.suggestions(bank.index, q)[0].text, "Saturn's rings");
    assert(!Quiz.suggestions(bank.index, q).some(x => ['Rings of Saturn', 'The rings of Saturn'].includes(x.text)));
  }
  assert.equal(Quiz.grade('Rings of Saturn', "Saturn's rings", true, bank.suppressedAnswers), 'prompt');
  assert.equal(JSON.stringify(original), before);
  assert(Quiz.suggestions(Quiz.questionBank(original, 'Moons of Saturn').index, 'rings of').some(x => x.text === 'Rings of Saturn'));
  assert.equal(Quiz.questionBank([], 'Pinned answer').index[0].text, 'Pinned answer');
});
// Minimal DOM exercises the actual progressive enhancement module and event handlers.
class Element {
  constructor() { this.attrs = {}; this.events = {}; this.children = []; this.hidden = true; this.value = ''; this.classList = {remove() {}}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, fn) { (this.events[k] ??= []).push(fn); }
  replaceChildren() { this.children = []; }
  append(e) { this.children.push(e); }
  focus() { this.focused = true; }
  scrollIntoView() {}
  fire(type, props = {}) { const e = {preventDefault() {this.prevented = true;}, stopPropagation() {}, ...props}; for (const f of this.events[type] || []) f(e); return e; }
}
test('keyboard completion, IME, escape and pointer stability', async () => {
  const input = new Element(), list = new Element(), status = new Element(), form = new Element();
  form.querySelector = s => ({'#id_typed_answer':input, '#answer-suggestions':list, '#answer-status':status}[s]);
  globalThis.document = {querySelector: s => s === '.typed-answer' ? form : {textContent: JSON.stringify({index: Quiz.answerIndex(fixtures.saturn)})}, createElement: () => new Element()};
  await import('../static/typed-answer.js');
  input.value = 'rings of'; input.fire('input');
  assert.equal(list.hidden, false);
  assert(input.fire('keydown', {key:'Enter'}).prevented);
  assert.equal(input.value, 'Rings of Saturn');
  assert(!input.fire('keydown', {key:'Enter'}).prevented);
  input.value = 'saturn'; input.fire('input');
  input.fire('keydown', {key:'ArrowDown'});
  assert(input.fire('keydown', {key:'Tab'}).prevented);
  input.fire('input'); input.fire('blur'); assert.equal(list.hidden, false);
  assert(input.fire('keydown', {key:'Escape'}).prevented); assert.equal(list.hidden, true);
  input.fire('input'); assert(!input.fire('keydown', {key:'Enter', isComposing:true}).prevented);
  input.fire('compositionstart'); assert(form.fire('submit').prevented);
  input.fire('compositionend'); assert(!form.fire('submit').prevented);
  assert(list.children[0].fire('pointerdown').prevented);
  list.children[0].fire('click'); assert.equal(list.hidden, true); assert(input.focused);
  delete globalThis.document;
});

test('Python and JavaScript normalization, filtering and grading parity', () => {
  const values = [...fixtures.distinct.flat(), ...fixtures.variants.flat(), ...fixtures.saturn,
    '  ANTONÍN   DVOŘÁK ', '1497–1498', 'Newton’s “laws”', 'e\u0301', 'x²', '±15', '1.25 meters'];
  const data = {values, grades: fixtures.grades, saturn: fixtures.saturn};
  const python = execFileSync(process.env.PYTHON || '.venv/bin/python', ['-c', `
import json, sys
from scholars.typed_answers import answer_key, search_key, wording_key, answer_index, question_bank, grade
f = json.load(sys.stdin)
print(json.dumps(dict(keys=[[answer_key(v), search_key(v), wording_key(v)] for v in f['values']],
    grades=[grade(g, c) for g, c, _ in f['grades']],
    index=question_bank(answer_index(f['saturn']), "Saturn's rings")['index'])))
`], {input: JSON.stringify(data), encoding:'utf8'});
  assert.deepEqual(JSON.parse(python), {
    keys: values.map(v => [Quiz.answerKey(v), Quiz.searchKey(v), Quiz.wordingKey(v)]),
    grades: fixtures.grades.map(([g,c]) => Quiz.grade(g,c)),
    index: Quiz.questionBank(Quiz.answerIndex(fixtures.saturn), "Saturn's rings").index
  });
});
