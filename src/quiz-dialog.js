import {Quiz} from './quiz.js';
import {esc} from './ui.js';
import {getPractice} from './data.js';
const quizDialog = document.querySelector('#quiz-dialog');
const quizBody = document.querySelector('#quiz-body');
let quizTimer, quizSession = 0;
document.querySelector('#quiz-close').addEventListener('click', () => quizDialog.close());
quizDialog.addEventListener('close', () => {
  clearTimeout(quizTimer); quizSession++;
  document.body.classList.remove('quiz-open');
});
export async function startQuiz(label, topicIds) {
  clearTimeout(quizTimer);
  const session = ++quizSession;
  document.querySelector('#quiz-title').textContent = label === 'Categories' ? 'All categories' : label;
  quizBody.innerHTML = '<p role="status">Loading questions…</p>';
  if (!quizDialog.open) quizDialog.showModal();
  document.body.classList.add('quiz-open');
  const active = () => quizDialog.open && session === quizSession;
  try {
    const data = await getPractice(topicIds);
    if (!active()) return;
    const selected = Quiz.select(data, topicIds);
    if (!selected.length) {quizBody.innerHTML = '<p>No practice questions available here yet.</p>'; return;}
    let index = 0, score = 0;
    const focusHeading = () => quizBody.querySelector('[tabindex="-1"]').focus();
    function next() {
      if (!active()) return;
      if (index === selected.length) {
        quizBody.innerHTML = `<h3 tabindex="-1">Score: ${score} / ${selected.length}</h3><button id="quiz-again">Quiz again</button>`;
        quizBody.querySelector('#quiz-again').addEventListener('click', () => startQuiz(label, topicIds));
        focusHeading(); return;
      }
      const q = selected[index];
      quizBody.innerHTML = `<p class="muted">Question ${index + 1} of ${selected.length}</p>${selected.length < 10 ? `<p class="muted">${selected.length} questions available in this selection.</p>` : ''}<h3 tabindex="-1">${esc(q.question)}</h3><div class="quiz-choices"></div><div role="status" aria-live="polite" class="quiz-feedback"></div>`;
      let answered = false;
      for (const choice of Quiz.choices(q)) {
        const button = document.createElement('button'); button.textContent = choice.text;
        quizBody.querySelector('.quiz-choices').append(button);
        button.addEventListener('click', () => {
          if (answered || !active()) return;
          answered = true; if (choice.correct) score++;
          quizBody.querySelector('h3').hidden = true;
          quizBody.querySelector('.quiz-choices').hidden = true;
          const feedback = quizBody.querySelector('.quiz-feedback');
          feedback.classList.add(choice.correct ? 'correct' : 'incorrect');
          feedback.innerHTML = `<strong>${choice.correct ? '✓ Correct!' : '✕ Incorrect'}</strong>${choice.correct ? '' : `<p>Correct answer: ${esc(q.correct_answer)}</p>`}`;
          index++;
          quizTimer = setTimeout(next, choice.correct ? 1000 : 1800);
        });
      }
      focusHeading();
    }
    next();
  } catch (error) {
    if (!active()) return;
    quizBody.innerHTML = `<p role="alert">${esc(error.message)}</p><button id="quiz-retry">Retry</button>`;
    quizBody.querySelector('#quiz-retry').addEventListener('click', () => startQuiz(label, topicIds));
  }
}

export function closeQuiz() { if (quizDialog.open) quizDialog.close(); }
