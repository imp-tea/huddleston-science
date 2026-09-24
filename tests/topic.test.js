import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import {topicHTML} from '../src/topic.js';

const read = path => JSON.parse(fs.readFileSync(new URL(`../data/${path}`, import.meta.url)));
const topics = read('topics.json');
const content = read('content.json');
const subs = new Map(read('taxonomy.json').subcategories.map(s => [s.subcategory_id, s]));

test('researched references render without inventing or linking an absent license', () => {
  const topic = topics.find(t => content[t.study_topic_id]?.source.references?.some(s => !s.license));
  assert(topic, 'Expected an enriched topic');
  const study = content[topic.study_topic_id];
  const html = topicHTML({...topic, study_content: study}, new URLSearchParams(), {topics}, subs);
  assert(html.includes('Key facts'));
  for (const source of study.source.references) {
    assert(html.includes(source.publisher));
  }
  assert(!html.includes('href=""'));
  assert(!html.includes('undefined'));
});

test('original licensed study notes still link to their recorded license and revision', () => {
  const topic = topics.find(t => content[t.study_topic_id]?.source.revision?.revid);
  const study = content[topic.study_topic_id];
  const html = topicHTML({...topic, study_content: study}, new URLSearchParams(), {topics}, subs);
  assert(html.includes(study.source.license_url));
  assert(html.includes(`oldid=${study.source.revision.revid}`));
});
