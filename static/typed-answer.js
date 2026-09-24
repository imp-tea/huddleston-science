import Quiz from './typed-matching.js';
const form = document.querySelector('.typed-answer');
const input = form.querySelector('#id_typed_answer');
const list = form.querySelector('#answer-suggestions');
const status = form.querySelector('#answer-status');
// The server prepares this view once from the pinned bank. Searches stay local.
const bank = JSON.parse(document.querySelector('#typed-bank').textContent).index;
input.setAttribute('role', 'combobox');
input.setAttribute('aria-autocomplete', 'list');
input.setAttribute('aria-expanded', 'false');
input.setAttribute('aria-controls', 'answer-suggestions');
let matches = [], highlighted = 0;
function close() {
  list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
}
function highlight() {
  [...list.children].forEach((option, i) => option.setAttribute('aria-selected', String(i === highlighted)));
  input.setAttribute('aria-activedescendant', `answer-option-${highlighted}`);
  list.children[highlighted]?.scrollIntoView({block:'nearest'});
}
function complete(i) {
  input.value = matches[i].text; close();
  status.classList.remove('answer-prompt');
  status.textContent = 'Answer selected. Press Enter or Check answer to submit.';
  input.focus();
}
function suggest() {
  status.classList.remove('answer-prompt');
  matches = Quiz.suggestions(bank, input.value); highlighted = 0;
  list.replaceChildren();
  for (const [i, match] of matches.entries()) {
    const option = document.createElement('li');
    option.id = `answer-option-${i}`; option.setAttribute('role', 'option'); option.textContent = match.text;
    option.addEventListener('pointerdown', event => event.preventDefault());
    option.addEventListener('click', () => complete(i));
    list.append(option);
  }
  list.hidden = matches.length === 0;
  input.setAttribute('aria-expanded', String(!list.hidden));
  if (matches.length) {
    highlight(); status.textContent = `${matches.length} suggestion${matches.length === 1 ? '' : 's'} available.`;
  } else {
    close(); status.textContent = Quiz.searchKey(input.value).length < 2 ? '' : 'No close matches. Try a different spelling or part of the answer, or skip.';
  }
}
input.addEventListener('input', event => { if (!event.isComposing) suggest(); });
input.addEventListener('compositionend', suggest);
// Keep the inline list in place on blur: collapsing it during pointerdown moves
// the submit button before pointerup and can swallow the user's click.
input.addEventListener('keydown', event => {
  if (event.isComposing) return;
  if (event.key === 'Escape' && !list.hidden) {event.preventDefault(); event.stopPropagation(); close();}
  else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (list.hidden) suggest();
    else {highlighted = (highlighted + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length; highlight();}
  } else if (!list.hidden && (event.key === 'Enter' || (event.key === 'Tab' && !event.shiftKey))) {
    event.preventDefault(); complete(highlighted);
  }
});
// Do not collapse on blur or submit: preserve pointer target placement.
let composing = false;
input.addEventListener('compositionstart', () => { composing = true; });
input.addEventListener('compositionend', () => { composing = false; });
form.addEventListener('submit', event => {
  if (composing) event.preventDefault();
});
