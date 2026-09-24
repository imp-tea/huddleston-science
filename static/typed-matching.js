'use strict';
// Matching rules ported from the quiz-bowl explorer; shared parity fixtures cover
// the server implementation. Suggestion scores never determine correctness.
const Quiz = {
  answerKey(value) {
    return value.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
      .replace(/[’‘]/g, "'").replace(/[“”]/g, '"').replace(/[–—−]/g, '-')
      .trim().replace(/\s+/g, ' ');
  },
  searchKey(value) {
    return Quiz.answerKey(value).replace(/[^\p{L}\p{N}+#/=<>%^*.\-]+/gu, ' ').trim().replace(/\s+/g, ' ');
  },
  wordingKey(value) {
    const key = Quiz.answerKey(value);
    // Do not reorder formulas, operators, or units expressed as ratios.
    if (/[\p{S}#/%^*]/u.test(key)) return null;
    const numbers = key.match(/[+-]?\p{N}+(?:[.,]\p{N}+)*/gu) || [];
    const words = key.replace(/(?<=\p{L})'s\b/gu, '').match(/[\p{L}\p{N}]+/gu) || [];
    // A in "A minor" is a musical key, not an article; keep interior A/An too.
    if (['a', 'an', 'the'].includes(words[0]) && !['major', 'minor'].includes(words[1])) words.shift();
    const content = words.filter(word => !['the', 'of'].includes(word));
    return content.length ? JSON.stringify([numbers, content.sort()]) : null;
  },
  questionBank(index, correctAnswer) {
    const expected = Quiz.answerKey(correctAnswer), wording = Quiz.wordingKey(correctAnswer);
    const suppressedAnswers = new Set();
    let foundCorrect = false;
    const filtered = index.map(entry => {
      if (Quiz.answerKey(entry.text) === expected) {
        foundCorrect = true;
        return {...entry, text: correctAnswer};
      }
      if (wording !== null && entry.wording === wording) {
        suppressedAnswers.add(Quiz.answerKey(entry.text));
        // Retain the original search key, but display only the question's answer.
        return {...entry, text: correctAnswer};
      }
      return entry;
    });
    if (!foundCorrect) filtered.push(...Quiz.answerIndex([correctAnswer]));
    return {index: filtered, suppressedAnswers};
  },
  grade(answer, correctAnswer, allowPrompt = true, suppressedAnswers = new Set()) {
    if (answer === null) return 'skipped';
    const given = Quiz.answerKey(answer), expected = Quiz.answerKey(correctAnswer);
    if (given === expected) return 'correct';
    if (allowPrompt && suppressedAnswers.has(given)) return 'prompt';
    if (!allowPrompt || given.length < 4 || given.length > 240) return 'incorrect';

    // A shared article or a few letters alone are not meaningful partial answers.
    const filler = new Set(['a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or', 'with', 'from', 'by', 'as', 'is', 'it', 'its', 'this', 'that']);
    const words = given.match(/\p{L}+/gu) || [];
    if (!words.some(word => word.length >= 4 && !filler.has(word))) return 'incorrect';

    // Close spelling must not excuse different quantities, formulas, or regnal numbers.
    const significant = text => (text.match(/[+-]?\p{N}+|[+#/=<>%^*]|\b[ivx]+\b/gu) || []).join('|');
    const givenSymbols = significant(given), expectedSymbols = significant(expected);
    if (givenSymbols && givenSymbols !== expectedSymbols) return 'incorrect';

    // Match a word or phrase beginning at a word boundary, including unfinished words.
    let start = expected.indexOf(given);
    while (start !== -1) {
      if (start === 0 || !/[\p{L}\p{N}]/u.test(expected[start - 1])) return 'prompt';
      start = expected.indexOf(given, start + 1);
    }
    if (givenSymbols !== expectedSymbols) return 'incorrect';
    // Use full-answer similarity here: autocomplete's prefix scores are too permissive.
    const length = Math.max(given.length, expected.length);
    if (Math.abs(given.length - expected.length) > length * 0.15) return 'incorrect';
    return 1 - Quiz.distance(given, expected) / length >= 0.85 ? 'prompt' : 'incorrect';
  },
  answerIndex(answers) {
    return answers.map(text => {
      const key = Quiz.searchKey(text);
      const words = key.split(' ');
      return {text, key, wording: Quiz.wordingKey(text), parts: words.map((_, i) => words.slice(i).join(' '))};
    });
  },
  // Optimal string alignment distance, including adjacent transpositions.
  distance(a, b, minPrefix = null) {
    let previous = Array.from({length: b.length + 1}, (_, i) => i), beforePrevious;
    for (let i = 1; i <= a.length; i++) {
      const row = [i];
      for (let j = 1; j <= b.length; j++) {
        row[j] = Math.min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
          row[j] = Math.min(row[j], beforePrevious[j - 2] + 1);
        }
      }
      beforePrevious = previous; previous = row;
    }
    return minPrefix === null ? previous[b.length] : Math.min(...previous.slice(minPrefix));
  },
  suggestions(index, value, limit = 5) {
    const query = Quiz.searchKey(value);
    if (query.length < 2 || query.length > 120) return [];
    const maxEdits = Math.min(4, Math.floor(query.length * 0.3));
    const results = new Map();
    for (const entry of index) {
      let score = 0;
      if (entry.key === query) score = 1;
      else if (entry.key.startsWith(query)) score = 0.96;
      else if (entry.parts.some(part => part.startsWith(query))) score = 0.92;
      else if (query.length >= 3 && entry.key.includes(query)) score = 0.84;
      // Never treat a changed digit as a spelling mistake.
      else if (maxEdits && !/\d/.test(query) && !/\d/.test(entry.key)) {
        let distance = maxEdits + 1;
        for (const part of entry.parts) {
          // Compare with nearby prefix lengths so unfinished, misspelled names work too.
          if (part.length < query.length - maxEdits) continue;
          distance = Math.min(distance, Quiz.distance(query, part.slice(0, query.length + maxEdits), Math.max(1, query.length - maxEdits)));
        }
        if (distance <= maxEdits) score = 0.8 - 0.6 * distance / query.length;
      }
      // Several searchable spellings may now point to the same display answer.
      if (score >= 0.6 && score > (results.get(entry.text)?.score ?? 0)) results.set(entry.text, {text: entry.text, score});
    }
    return [...results.values()].sort((a, b) => b.score - a.score || a.text.length - b.text.length || a.text.localeCompare(b.text)).slice(0, limit);
  }
};
export default Quiz;
