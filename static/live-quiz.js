import {attachAutocomplete} from './typed-answer.js?v=live-quiz-4';
import {acceptState, isCurrentQuestion, retryDelay} from './live-sync.js';

const root = document.querySelector('#live-quiz');
const get = id => document.getElementById(id);
const base = root.dataset.base, hosting = root.dataset.host === 'true';
const csrf = root.querySelector('[name=csrfmiddlewaretoken]').value;
const connection = crypto.randomUUID();
const form = get('live-answer'), input = get('id_typed_answer');
const autocomplete = attachAutocomplete(form, []);
let current = null, connected = false, stopped = false, pollBusy = false, heartbeatBusy = false;
let timer, heartTimer, failures = 0, bankPosition = 0, actionBusy = false, answerBusy = false;
let pendingControl = null, confirmation = null;
const finalized = new Map();

function error(message = '') { get('live-error').textContent = message; get('live-error').hidden = !message; }
function show(id, visible) { const node = get(id); if (node) node.hidden = !visible; }
async function request(path, values) {
  const response = await fetch(base + path, {method: values ? 'POST' : 'GET', cache: 'no-store',
    headers: {'Accept': 'application/json'}, body: values ? new URLSearchParams({csrfmiddlewaretoken: csrf, ...values}) : undefined,
    signal: AbortSignal.timeout(8000)});
  if (response.status >= 500) throw new Error('Server temporarily unavailable. Reconnecting…');
  if (!response.headers.get('content-type')?.includes('application/json')) {
    const err = new Error('Your sign-in may have expired. Reload this page to sign in again.'); err.fatal = true; throw err;
  }
  const data = await response.json();
  if (!response.ok) {
    const err = new Error(data.error || 'Could not update the quiz. Try again.');
    err.fatal = response.status === 403 || response.status === 404;
    err.conflict = response.status === 409;
    throw err;
  }
  return data;
}
function failure(err) {
  error(err.message || 'Connection lost. Trying again…');
  if (err.fatal) { stopped = true; clearTimeout(timer); clearTimeout(heartTimer); }
}
function render(data) {
  if (!acceptState(current, data)) return;
  const changed = !current || data.position !== current.position;
  current = data;
  if (pendingControl && data.version > pendingControl.version) pendingControl = null;
  if (changed) {
    bankPosition = 0; input.value = ''; autocomplete.setBank([]);
    get('answer-status').textContent = ''; confirmation = null; show('live-confirm', false);
  }
  get('live-network').textContent = data.phase === 'finished' || data.phase === 'cancelled' ? 'Results saved.' : 'Connected · Updates automatically';
  show('live-lobby', data.phase === 'waiting');
  show('live-question', data.phase === 'running');
  show('live-finished', data.phase === 'finished' || data.phase === 'cancelled');
  show('live-leave', data.phase === 'waiting' || data.phase === 'running');
  get('live-host-presence').textContent = !hosting && !data.host_present && ['waiting', 'running'].includes(data.phase)
    ? 'The teacher is away. Your place and answers are saved; the quiz waits for them to return.' : '';
  get('live-roster-title').textContent = data.phase === 'waiting' ? `${data.connected} student${data.connected === 1 ? '' : 's'} waiting` : `${data.connected} of ${data.roster_count} players connected`;
  get('live-players').replaceChildren(...data.players.map(player => {
    const li = document.createElement('li');
    li.textContent = `${player.name} · ${player.presence === 'connected' ? 'Connected' : player.presence === 'away' ? 'Away / reconnecting' : 'Left'}${hosting && data.phase === 'running' ? (player.answered ? ' · Answered or skipped' : ' · Waiting for answer') : ''}`;
    return li;
  }));
  if (data.phase === 'running') {
    get('live-position').textContent = `Question ${data.position} of ${data.total}`;
    get('live-prompt').textContent = data.question.prompt;
    show('live-tally', hosting);
    if (hosting) get('live-tally').textContent = `${data.answered} of ${data.roster_count} answered or skipped · ${data.roster_count - data.answered} still unanswered`;
    const response = data.response || finalized.get(data.position);
    show('live-feedback', !hosting && Boolean(response));
    if (response) get('live-feedback').textContent = ({correct: 'Correct!', incorrect: 'Incorrect.', skipped: 'Skipped.', unanswered: 'No answer before advance.'}[response.status] || '') + ' Waiting for the next question.';
    show('live-answer', !hosting && !response && bankPosition === data.position);
    form.querySelectorAll('button').forEach(b => { b.disabled = answerBusy; });
  } else show('live-answer', false);
  if (hosting) {
    show('live-start', data.phase === 'waiting'); show('live-cancel', data.phase === 'waiting');
    show('live-next', data.phase === 'running'); show('live-end', data.phase === 'running' && data.position < data.total);
    get('live-start').disabled = actionBusy || data.connected === 0;
    for (const id of ['live-next', 'live-end', 'live-cancel', 'live-confirm-yes']) get(id).disabled = actionBusy;
    get('live-next').textContent = data.position === data.total ? 'Finish Quiz' : 'Next Question';
  }
  if (data.phase === 'finished' || data.phase === 'cancelled') {
    clearTimeout(heartTimer);
    show('live-confirm', false);
    get('live-finished-title').textContent = data.phase === 'cancelled' ? 'Quiz cancelled' : (data.summary.partial ? 'Quiz ended early' : 'Quiz complete!');
    get('live-score').textContent = data.summary ? (hosting ? '' : `Your score: ${data.summary.score}/${data.summary.presented}. `) + (data.summary.partial ? `${data.summary.presented} of ${data.total} questions presented.` : `${data.total} questions played.`) : 'The waiting room was closed before play began.';
    show('live-report', Boolean(data.report_url));
    if (data.report_url) get('live-report').href = data.report_url;
    show('live-cohort-note', Boolean(data.cohort_note));
    get('live-cohort-note').textContent = data.cohort_note || '';
    get('live-team').textContent = data.summary ? `Team coverage: ${data.summary.covered}/${data.summary.presented} (${data.summary.coverage_percent}%) answered correctly by at least one player.` : '';
  }
}
async function loadBank() {
  if (hosting || current?.phase !== 'running' || current.response || finalized.has(current.position) || bankPosition === current.position) return;
  const position = current.position;
  try {
    const data = await request(`suggestions/${position}/`);
    if (stopped || !isCurrentQuestion(current, position) || data.version < current.version) return;
    autocomplete.setBank(data.index); bankPosition = position; render(current);
  } catch (err) { if (!err.conflict) throw err; }
}
async function pulse() {
  if (stopped || heartbeatBusy || !connected || !['waiting', 'running'].includes(current?.phase)) return;
  heartbeatBusy = true;
  try { await request('heartbeat/', {connection}); }
  catch (err) {
    if (!stopped && ['waiting', 'running'].includes(current?.phase)) {
      if (err.conflict) poll(); else failure(err);
    }
  }
  finally {
    heartbeatBusy = false;
    if (!stopped && ['waiting', 'running'].includes(current?.phase)) heartTimer = setTimeout(pulse, 5000);
  }
}
async function poll() {
  if (stopped || pollBusy) return;
  pollBusy = true; clearTimeout(timer);
  try {
    const data = await request('state/');
    if (stopped) return;
    if (!connected && ['waiting', 'running'].includes(data.phase)) {
      await request('connect/', {connection}); connected = true;
    }
    render(data); if (!heartTimer && connected) pulse();
    await loadBank(); if (failures) error(); failures = 0;
  } catch (err) { failures++; get('live-network').textContent = 'Connection interrupted · Reconnecting…'; failure(err); }
  finally {
    pollBusy = false;
    if (!stopped && !['finished', 'cancelled'].includes(current?.phase)) timer = setTimeout(poll, retryDelay(failures) + Math.random() * 300);
  }
}
async function control(action) {
  if (actionBusy || !current) return;
  actionBusy = true; error();
  const values = pendingControl || {action, version: current.version, position: current.position, request_key: crypto.randomUUID()};
  pendingControl = values; render(current);
  try { await request('control/', values); pendingControl = null; show('live-confirm', false); }
  catch (err) { if (err.conflict) pendingControl = null; failure(err); }
  finally { actionBusy = false; render(current); poll(); }
}
if (hosting) {
  get('live-start').addEventListener('click', () => control('start'));
  get('live-next').addEventListener('click', () => control('next'));
  for (const [id, action, text] of [['live-end', 'end', 'End now? Unanswered responses on this question count as unanswered. Later questions will not count.'], ['live-cancel', 'cancel', 'Cancel this waiting room? No game results will be scored.']]) {
    get(id).addEventListener('click', () => { confirmation = action; get('live-confirm-text').textContent = text; show('live-confirm', true); });
  }
  get('live-confirm-no').addEventListener('click', () => { confirmation = null; show('live-confirm', false); });
  get('live-confirm-yes').addEventListener('click', () => { if (confirmation) control(confirmation); });
}
form.addEventListener('submit', async event => {
  if (event.defaultPrevented) return;
  event.preventDefault();
  if (answerBusy || !current || finalized.has(current.position)) return;
  const position = current.position;
  const action = event.submitter?.value || 'answer';
  answerBusy = true; error(); render(current);
  try {
    const data = await request('answer/', {position, action, typed_answer: input.value});
    if (stopped || !isCurrentQuestion(current, position)) return;
    if (data.outcome === 'prompt') {
      get('answer-status').textContent = 'Please be more specific or check the spelling, then try again.';
      get('answer-status').classList.add('answer-prompt'); input.focus();
    } else {
      finalized.set(position, {status: data.outcome}); render(current);
    }
  } catch (err) { failure(err); }
  finally { answerBusy = false; if (current) render(current); poll(); }
});
function beaconLeave() {
  if (!connected) return;
  navigator.sendBeacon(base + 'leave/', new URLSearchParams({csrfmiddlewaretoken: csrf, connection}));
}
get('live-leave').addEventListener('click', async () => {
  stopped = true; clearTimeout(timer); clearTimeout(heartTimer);
  try { await request('leave/', {connection}); } catch { beaconLeave(); }
  window.location.assign(root.dataset.home);
});
window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); clearTimeout(heartTimer); beaconLeave(); });
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
window.addEventListener('focus', () => { if (!stopped) { poll(); if (!heartbeatBusy) { clearTimeout(heartTimer); pulse(); } } });
poll();
