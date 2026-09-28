"""Constrained sampling with augmenting paths, not a greedy shortage estimate."""
from collections import Counter, defaultdict, deque
import random

from django.core.exceptions import ValidationError

from .question_selection import group_questions
from .quiz_forms import RandomQuizForm
from .quiz_lists import available_questions

rng = random.SystemRandom()


class Shortage(ValidationError):
    def __init__(self, requested, available):
        self.available = available
        super().__init__(f'Only {available} questions are available under these filters and duplicate/topic limits; '
                         f'{requested} were requested. Reduce the count or relax the filters and try again.')


class Flow:
    def __init__(self):
        self.edges = defaultdict(list)

    def add(self, source, target, capacity):
        forward = [target, capacity, None]
        reverse = [source, 0, forward]
        forward[2] = reverse
        self.edges[source].append(forward)
        self.edges[target].append(reverse)
        return forward

    def fill(self, limit):
        total = 0
        while total < limit:
            parents = {'source': None}
            queue = deque(['source'])
            while queue and 'sink' not in parents:
                node = queue.popleft()
                for edge in self.edges[node]:
                    target, remaining, _ = edge
                    if remaining and target not in parents:
                        parents[target] = (node, edge)
                        queue.append(target)
            if 'sink' not in parents:
                break
            node = 'sink'
            while node != 'source':
                source, edge = parents[node]
                edge[1] -= 1
                edge[2][1] += 1
                node = source
            total += 1
        return total


def generate(data):
    form = RandomQuizForm(data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    settings = form.cleaned_data
    count = settings['count']
    questions = available_questions().filter(topic__category_id__in=settings['categories'])
    if settings['subcategories']:
        questions = questions.filter(topic__subcategories__pk__in=settings['subcategories']).distinct()
    questions = list(questions.select_related('topic', 'current_revision').only('id', 'difficulty', 'topic_id', 'current_revision_id', 'current_revision__payload', 'topic__id', 'topic__title', 'topic__category_id').order_by('pk'))
    groups = (group_questions(questions, lambda q: q.current_revision.payload)
              if settings['exclude_duplicates'] else [[q] for q in questions])
    rng.shuffle(groups)
    categories = list(settings['categories'])
    rng.shuffle(categories)
    quotas = {c: count // len(categories) + (i < count % len(categories)) for i, c in enumerate(categories)}
    flow = Flow()
    group_edges = []
    topics = {}
    for index, group in enumerate(groups):
        group_node = ('group', index)
        flow.add('source', group_node, 1)
        by_topic = defaultdict(list)
        for q in group:
            by_topic[q.topic_id].append(q)
            topics[q.topic_id] = q.topic.category_id
        candidates = list(by_topic.items())
        rng.shuffle(candidates)
        for topic_id, variants in candidates:
            edge = flow.add(group_node, ('topic', topic_id), 1)
            group_edges.append((edge, variants))
    for topic_id, category in topics.items():
        flow.add(('topic', topic_id), ('category', category), settings['max_per_topic'] or count)
    balanced = settings['distribution'] == 'balanced'
    category_edges = {c: flow.add(('category', c), 'sink', quotas[c] if balanced else count) for c in categories}
    total = flow.fill(count)
    # Gradually relax quotas, retaining residual edges so earlier choices can move
    # between topics/categories. This finds real capacity even across duplicates.
    if balanced:
        for _ in range(count):
            if total == count:
                break
            for edge in category_edges.values():
                edge[1] += 1
            total += flow.fill(count - total)
    if total != count:
        raise Shortage(count, total)
    selected = [rng.choice(variants) for edge, variants in group_edges if edge[2][1]]
    targets = difficulty_targets(settings, count)
    selected = fit_difficulty(selected, groups, targets, settings)
    rng.shuffle(selected)
    counts = Counter(q.topic.category_id for q in selected)
    distribution = [{'category': c, 'target': quotas[c], 'actual': counts[c]} for c in sorted(categories)]
    difficulty_counts = Counter(q.difficulty for q in selected)
    difficulty_distribution = [{'label': level.title(), 'target': targets[level], 'actual': difficulty_counts[level]}
                               for level in ('easy', 'medium', 'hard')]
    if difficulty_counts['']:
        difficulty_distribution.append({'label': 'Not rated', 'target': 0, 'actual': difficulty_counts['']})
    return {'difficulty_distribution': difficulty_distribution,
            'difficulty_adjusted': any(row['target'] != row['actual'] for row in difficulty_distribution),
            'questions': selected, 'settings': settings, 'distribution': distribution,
            'redistributed': balanced and any(counts[c] != quotas[c] for c in categories)}


def difficulty_targets(settings, count):
    """Largest remainders keep rounded whole-question targets summing to count."""
    levels = ['easy', 'medium', 'hard']
    weights = [settings['difficulty_' + level] for level in levels]
    exact = [count * weight / sum(weights) for weight in weights]
    targets = [int(value) for value in exact]
    # Randomize equal remainders, avoiding a systematic Easy bias on short quizzes.
    order = list(range(3))
    rng.shuffle(order)
    order.sort(key=lambda i: exact[i] - targets[i], reverse=True)
    for i in order[:count - sum(targets)]:
        targets[i] += 1
    return dict(zip(levels, targets))


def fit_difficulty(selected, groups, targets, settings):
    """Improve the soft difficulty target without weakening any existing limits.

    Start with the capacity-proven flow selection. Each exchange reduces a
    difficulty deficit while retaining category shares, topic caps and duplicate
    groups. This is a best-effort local fit, not a global optimality guarantee.
    Unrated questions count as fallback only, never as an inferred difficulty.
    """
    selected = list(selected)
    group_for = {q.pk: index for index, group in enumerate(groups) for q in group}
    used = {group_for[q.pk] for q in selected}
    topics = Counter(q.topic_id for q in selected)
    counts = Counter(q.difficulty for q in selected)
    candidates = defaultdict(list)
    for group in groups:
        for q in group:
            candidates[q.difficulty].append(q)
    for pool in candidates.values():
        rng.shuffle(pool)
    while True:
        changed = False
        for level in sorted(targets, key=lambda key: targets[key] - counts[key], reverse=True):
            if counts[level] >= targets[level]:
                continue
            for candidate in candidates[level]:
                group = group_for[candidate.pk]
                for index, old in enumerate(selected):
                    if counts[old.difficulty] <= targets.get(old.difficulty, 0):
                        continue
                    old_group = group_for[old.pk]
                    if group in used and group != old_group:
                        continue
                    if settings['distribution'] == 'balanced' and candidate.topic.category_id != old.topic.category_id:
                        continue
                    cap = settings['max_per_topic']
                    if cap and candidate.topic_id != old.topic_id and topics[candidate.topic_id] >= cap:
                        continue
                    selected[index] = candidate
                    used.remove(old_group)
                    used.add(group)
                    topics[old.topic_id] -= 1
                    topics[candidate.topic_id] += 1
                    counts[old.difficulty] -= 1
                    counts[level] += 1
                    changed = True
                    break
                if changed:
                    break
            if changed:
                break
        if not changed:
            return selected
