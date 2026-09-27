// Shared, testable guards for delayed polling and answer responses.
export function acceptState(current, incoming) {
  return !current || (current.id === incoming.id && incoming.version >= current.version);
}
export function isCurrentQuestion(state, position) {
  return state?.phase === 'running' && state.position === position;
}
export function retryDelay(failures) {
  return Math.min(15000, 2000 * 2 ** Math.min(failures, 3));
}
