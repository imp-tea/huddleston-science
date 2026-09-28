import test from 'node:test';
import assert from 'node:assert/strict';
import {vertices, weightsAt, projectPoint, percentages} from '../static/quiz-generator.js';
const close = (a, b) => a.forEach((value, i) => assert.ok(Math.abs(value - b[i]) < 1e-9));
test('triangle vertices, center and edge give the requested proportions', () => {
  vertices.forEach((point, i) => close(weightsAt(...point), [0, 1, 2].map(j => +(j === i))));
  close(weightsAt(170, (250 + 250 + 24) / 3), [1 / 3, 1 / 3, 1 / 3]);
  close(weightsAt(170, 250), [.5, .5, 0]);
});
test('dragging outside stays on the triangle with nonnegative weights', () => {
  for (const point of [[-100, 500], [1000, -300], [170, -50], [170, 900], [0, 120]]) {
    const weights = weightsAt(...projectPoint(...point));
    assert.ok(weights.every(w => w >= -1e-9 && w <= 1 + 1e-9));
    assert.ok(Math.abs(weights.reduce((a, b) => a + b) - 1) < 1e-9);
  }
  close(projectPoint(170, -100), vertices[2]);
});
test('readout percentages sum to 100 including the equal split', () => {
  for (const weights of [[1, 1, 1], [32, 57, 11], [0, 0, 1], [.1, .2, .7]]) {
    assert.equal(percentages(weights).reduce((a, b) => a + b), 100);
  }
  assert.deepEqual(percentages([32, 57, 11]), [32, 57, 11]);
});
