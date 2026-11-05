import test from 'node:test';
import assert from 'node:assert/strict';
import { snapshotFor, operationId, validateSnapshots } from '../src/data/review.ts';

test('review uses topic version, preserves complete memory and adjusts sources after moving', () => {
  const topic = { topic_id: 'old' };
  const summary = { version: 7, overview: 'Keep context', proposals: ['Plan'], decisions: ['Done'], open_questions: ['When?'], action_items: ['Ship'], source_message_ids: ['m1', 'm2'] };
  const old = snapshotFor(topic.topic_id, summary, 12, 'm2', 'new', 'old');
  assert.equal(old.expected_version, 12);
  assert.equal(old.overview, 'Keep context');
  assert.deepEqual(old.decisions, ['Done']);
  assert.deepEqual(old.source_message_ids, ['m1']);
  const target = snapshotFor('new', { overview: 'Other', source_message_ids: ['m3'] }, 3, 'm2', 'new', 'old');
  assert.deepEqual(target.source_message_ids, ['m3', 'm2']);
  const same = snapshotFor('old', summary, 12, 'm2', 'old', 'old');
  assert.deepEqual(same.source_message_ids, ['m1', 'm2']);
  assert.throws(() => validateSnapshots([{ ...old, source_message_ids: [] }]), /nguồn/);
  assert.throws(() => validateSnapshots([{ ...old, source_message_ids: ['m1', 'm1'] }]), /trùng/);
});

test('same request retry retains request_id; editing the command creates a new one', () => {
  const draft = {};
  const first = operationId(draft, { reason: 'fix', expected_revision: 2 });
  assert.equal(operationId(draft, { reason: 'fix', expected_revision: 2 }), first);
  assert.notEqual(operationId(draft, { reason: 'changed', expected_revision: 2 }), first);
});
