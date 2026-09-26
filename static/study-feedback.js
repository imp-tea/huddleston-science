/* The answer has already been saved; this page only briefly presents its result.
   Without JavaScript, Continue leads to the persisted next question or result. */
const next = document.querySelector('[data-quiz-continue]');
if (next) {
  document.querySelector('#feedback-heading').focus();
  window.setTimeout(() => window.location.replace(next.href), 1200);
}
