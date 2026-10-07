import test from 'node:test';
import assert from 'node:assert/strict';
import {acceptState, isCurrentQuestion, retryDelay, pointsAvailable} from '../static/live-sync.js';

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

test('the clock uses server-provided reading grace and then eases to 25 points', () => {
  // Fractional grace is shared by the ready response and subsequent state polls.
  for (const grace of [5, 5.78, 11.5, 18]) {
    assert.equal(pointsAvailable(0, grace), 100);
    assert.equal(pointsAvailable(grace - .1, grace), 100);
    for (const [seconds, points] of [[0,100], [1,90], [3,73], [7.5,44], [10,33], [15,25], [100,25]]) {
      assert.equal(pointsAvailable(grace + seconds, grace), points);
    }
  }
});
test('same-version snapshots cannot undo an expired reveal or newer score', () => {
  const current = {id:'a', version:2, position:2, server_now:'2026-10-07T15:00:04+00:00'};
  assert.equal(acceptState(current, {...current, server_now:'2026-10-07T15:00:03+00:00'}), false);
  assert.equal(isCurrentQuestion({...current, phase:'running', revealing:true}, 2), false);
});
