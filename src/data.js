// Only the browse index loads at startup. Detail and quiz files are cached on demand.
let corpus;
const requests = new Map();
async function json(path) {
  if (!requests.has(path)) {
    requests.set(path, fetch(path, {cache:'no-cache'}).then(response => {
      if (!response.ok) throw new Error('Unable to load website data. Please try again.');
      return response.json();
    }).catch(error => {requests.delete(path); throw error;}));
  }
  return requests.get(path);
}
export async function loadCorpus() {
  corpus = await json('data/index.json');
  return corpus;
}
export async function getTopic(id) {
  const topic = corpus.topics.find(t => t.study_topic_id === id);
  if (!topic) throw new Error('Topic not found');
  const details = await json(corpus.assets[topic.primary_category].details);
  return details[id];
}
export async function getPractice(topicIds) {
  const categories = new Set(corpus.topics.filter(t => topicIds.has(t.study_topic_id)).map(t => t.primary_category));
  return (await Promise.all([...categories].map(c => json(corpus.assets[c].practice)))).flat();
}
export async function getSources(ids) {
  const prefixes = new Set(ids.map(id => id.slice(3,4)));
  const shards = await Promise.all([...prefixes].map(p => json(corpus.source_shards[p])));
  return Object.assign({}, ...shards);
}
