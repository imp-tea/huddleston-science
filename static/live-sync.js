// Shared, testable guards for delayed polling and answer responses.
export function acceptState(current, incoming) {
  return !current || (current.id === incoming.id && (incoming.version > current.version || (incoming.version === current.version
    && (!current.server_now || !incoming.server_now || incoming.server_now >= current.server_now))));
}
export function isCurrentQuestion(state, position) {
  return state?.phase === 'running' && !state.revealing && state.position === position;
}
export function retryDelay(failures) {
  return Math.min(15000, 2000 * 2 ** Math.min(failures, 3));
}

export function pointsAvailable(elapsed) {
  const seconds = Math.min(15, Math.max(0, elapsed - 3));
  return Math.round(100 - 10 * seconds + seconds * seconds / 3);
}
