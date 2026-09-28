// Barycentric weights: each vertex is 100%, and the opposite edge is 0%.
export const vertices = [[40, 250], [300, 250], [170, 24]];
export function weightsAt(x, y) {
  const hard = (250 - y) / 226;
  const medium = (x - 40 - 130 * hard) / 260;
  return [1 - medium - hard, medium, hard];
}
export function projectPoint(x, y) {
  if (weightsAt(x, y).every(value => value >= 0)) return [x, y];
  let closest, distance = Infinity;
  vertices.forEach((a, i) => {
    const b = vertices[(i + 1) % 3];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)));
    const point = [a[0] + t * dx, a[1] + t * dy];
    const d = (x - point[0]) ** 2 + (y - point[1]) ** 2;
    if (d < distance) { closest = point; distance = d; }
  });
  return closest;
}
export function percentages(weights) {
  const sum = weights.reduce((a, b) => a + b, 0);
  const exact = weights.map(value => 100 * value / sum);
  const rounded = exact.map(Math.floor);
  const order = [0, 1, 2].sort((a, b) => (exact[b] - rounded[b]) - (exact[a] - rounded[a]));
  const remainder = 100 - rounded.reduce((a, b) => a + b, 0);
  for (let i = 0; i < remainder; i++) rounded[order[i]]++;
  return rounded;
}

if (typeof document !== 'undefined') {
  const form = document.querySelector('.quiz-generator');
  if (form) {
    const graph = form.querySelector('.difficulty-graph');
    const svg = graph.querySelector('svg');
    const dot = graph.querySelector('.mix-dot');
    const output = graph.querySelector('output');
    const inputs = ['easy', 'medium', 'hard'].map(level => form.elements['difficulty_' + level]);
    let point = [170, 174.667];
    function render() {
      const weights = inputs.map(input => Number(input.value));
      if (inputs.some(input => input.value === '' || !input.validity.valid) || weights.some(w => !Number.isFinite(w) || w < 0) || weights.reduce((a, b) => a + b, 0) <= 0) {
        output.textContent = 'Enter three valid weights, with at least one above zero.';
        return;
      }
      const sum = weights.reduce((a, b) => a + b, 0);
      point = [0, 1].map(axis => vertices.reduce((value, vertex, i) => value + vertex[axis] * weights[i] / sum, 0));
      dot.setAttribute('cx', point[0]); dot.setAttribute('cy', point[1]);
      const p = percentages(weights);
      output.textContent = `${p[0]}% Easy, ${p[1]}% Medium, ${p[2]}% Hard`;
    }
    function move(x, y) {
      // A small hit area makes exact 100% corners easy to reach by touch.
      const corner = vertices.find(vertex => Math.hypot(x - vertex[0], y - vertex[1]) <= 6);
      const p = corner || projectPoint(x, y);
      weightsAt(...p).forEach((weight, i) => { inputs[i].value = Math.max(0, Math.min(100, weight * 100)).toFixed(2); });
      render();
    }
    function pointer(event) {
      const matrix = svg.getScreenCTM();
      if (!matrix) return;
      const local = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      move(local.x, local.y);
    }
    svg.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault(); svg.focus(); svg.setPointerCapture(event.pointerId); pointer(event);
    });
    svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) pointer(event); });
    svg.addEventListener('pointerup', event => {
      if (svg.hasPointerCapture(event.pointerId)) { pointer(event); svg.releasePointerCapture(event.pointerId); }
    });
    svg.addEventListener('keydown', event => {
      const delta = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
      if (event.key === 'Home') { event.preventDefault(); inputs.forEach(input => { input.value = 1; }); render(); }
      else if (delta) { event.preventDefault(); const step = event.shiftKey ? 15 : 3; move(point[0] + step * delta[0], point[1] + step * delta[1]); }
    });
    inputs.forEach(input => input.addEventListener('input', render));
    graph.hidden = false; render();

    const mapping = JSON.parse(document.getElementById('subcategory-categories').textContent);
    const categories = [...form.querySelectorAll('[name="categories"]')];
    const subcategories = [...form.querySelectorAll('[name="subcategories"]')];
    const empty = document.createElement('p');
    empty.className = 'muted'; empty.textContent = 'Select a category above to see its subcategories.';
    form.querySelector('#id_subcategories').after(empty);
    function filterSubcategories() {
      const selected = new Set(categories.filter(input => input.checked).map(input => input.value));
      let visible = 0;
      subcategories.forEach(input => {
        const show = selected.has(mapping[input.value]);
        input.closest('label').parentElement.hidden = !show;
        input.disabled = !show;
        if (!show) input.checked = false;
        else visible++;
      });
      empty.hidden = visible > 0;
      empty.textContent = selected.size ? 'No subcategories available for these categories.' : 'Select a category above to see its subcategories.';
    }
    categories.forEach(input => input.addEventListener('change', filterSubcategories));
    filterSubcategories();
  }
}
