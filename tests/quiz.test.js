import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import {Quiz} from '../src/quiz.js';
const root = new URL('../',import.meta.url);
const read = path => JSON.parse(fs.readFileSync(new URL(path,root)));
const topics=read('data/topics.json');
const taxonomy=read('data/taxonomy.json');
const questions=fs.readdirSync(new URL('data/practice/',root)).flatMap(f=>read('data/practice/'+f));

test('all category and subcategory pools remain scoped, capped, and nonrepeating',()=>{
  const scopes=[topics,...taxonomy.categories.map(c=>topics.filter(t=>t.primary_category===c.primary_category)),...taxonomy.subcategories.map(s=>topics.filter(t=>t.subcategory_ids.includes(s.subcategory_id)))];
  for(const scope of scopes){
    const ids=new Set(scope.map(t=>t.study_topic_id));
    const selected=Quiz.select(questions,ids,()=>0.37);
    assert.equal(selected.length,Math.min(10,questions.filter(q=>ids.has(q.study_topic_id)).length));
    assert.equal(new Set(selected.map(q=>q.question_id)).size,selected.length);
    assert(selected.every(q=>ids.has(q.study_topic_id)));
  }
  assert.deepEqual(Quiz.select(questions,new Set()),[]);
});
test('shuffling preserves all four options and exactly one correct answer',()=>{
  for(const q of questions){
    const choices=Quiz.choices(q,()=>0.37);
    assert.equal(choices.length,4);
    assert.equal(new Set(choices.map(c=>c.text)).size,4);
    assert.equal(choices.filter(c=>c.correct).length,1);
    assert.equal(choices.find(c=>c.correct).text,q.correct_answer);
  }
  const original=[1,2,3,4];
  assert.deepEqual(Quiz.shuffle(original,()=>0),[2,3,4,1]);
  assert.deepEqual(original,[1,2,3,4]);
});
test('data loader fetches only needed shards, caches them, and retries failures',async()=>{
  const calls=[];
  let fail=false;
  globalThis.fetch=async path=>{
    calls.push(path);
    if(fail){fail=false; return {ok:false};}
    return {ok:true,json:async()=>read('dist/'+path)};
  };
  const api=await import('../src/data.js');
  const index=await api.loadCorpus();
  assert.deepEqual(calls,['data/index.json']);
  const t=topics.find(t=>t.primary_category==='Geography');
  fail=true;
  await assert.rejects(api.getTopic(t.study_topic_id));
  const detail=await api.getTopic(t.study_topic_id);
  assert.equal(detail.topic,t.topic);
  const previous=calls.length;
  await api.getTopic(t.study_topic_id);
  assert.equal(calls.length,previous);
  const pool=await api.getPractice(new Set([t.study_topic_id]));
  assert.equal(calls.at(-1),index.assets.Geography.practice);
  const geoIds=new Set(topics.filter(t=>t.primary_category==='Geography').map(t=>t.study_topic_id));
  assert(pool.every(q=>geoIds.has(q.study_topic_id)));
  const sources=await api.getSources(t.source_ids);
  assert(t.source_ids.every(id=>sources[id].custom_id===id));
});
