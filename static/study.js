/* Progressive enhancement only; reading, quizzes, and saves work without JS. */
document.addEventListener('click', event => {
  const button = event.target.closest('[data-select-all]');
  if (button) button.closest('form').querySelectorAll('input[name="categories"]').forEach(input => { input.checked = true; });
});
