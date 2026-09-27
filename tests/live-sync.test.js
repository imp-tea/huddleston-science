import test from 'node:test';
import assert from 'node:assert/strict';
import {acceptState, isCurrentQuestion, retryDelay} from '../static/live-sync.js';

test('delayed state cannot move a game backwards or cross games', () => {
  const current = {id:'a', version:5, position:3, phase:'running'};
  assert.equal(acceptState(current, {...current, version:4}), false);
  assert.equal(acceptState(current, {...current, id:'b'}), false);
  assert.equal(acceptState(current, {...current, version:6}), true);
  assert.equal(acceptState(current, {...current}), true);
});
test('answer feedback is valid only for the currently open question', () => {
  assert.equal(isCurrentQuestion({phase:'running', position:2}, 1), false);
  assert.equal(isCurrentQuestion({phase:'finished', position:2}, 2), false);
  assert.equal(isCurrentQuestion({phase:'running', position:2}, 2), true);
});
test('poll backoff is bounded', () => {
  assert.equal(retryDelay(0), 2000);
  assert.equal(retryDelay(1), 4000);
  assert.equal(retryDelay(100), 15000);
});
