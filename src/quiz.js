'use strict';
export const Quiz = {
  shuffle(items, random = Math.random) {
    const result = [...items];
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  },
  select(questions, topicIds, random = Math.random) {
    return Quiz.shuffle(questions.filter(q => topicIds.has(q.study_topic_id)), random).slice(0, 10);
  },
  choices(question, random = Math.random) {
    return Quiz.shuffle([
      {text: question.correct_answer, correct: true},
      ...question.distractors.map(text => ({text, correct: false}))
    ], random);
  }
};
