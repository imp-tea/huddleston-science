import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';

test('saved-answer feedback focuses the result and continues without resubmitting', () => {
  const href = '/scholars-bowl/study/saved-session/';
  let focused = false, callback, delay, destination;
  const context = {
    document: {querySelector: selector => selector === '[data-quiz-continue]' ? {href} : {focus: () => { focused = true; }}},
    window: {setTimeout: (fn, ms) => {callback = fn; delay = ms;}, location: {replace: url => {destination = url;}}},
  };
  vm.runInNewContext(fs.readFileSync(new URL('../static/study-feedback.js', import.meta.url), 'utf8'), context);
  assert(focused);
  assert.equal(destination, undefined);
  assert.equal(delay, 1200);
  callback();
  assert.equal(destination, href);
});
