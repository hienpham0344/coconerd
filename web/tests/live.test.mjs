import test from 'node:test';
import assert from 'node:assert/strict';
import { liveClient } from '../src/data/live.ts';

test('live reads use private routes and guild scope; failures cannot fall back to demo', async t => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  const calls = [];
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    if (path.includes('/summary')) return new Response('{"detail":"No summary"}', { status: 404 });
    return new Response('{"detail":"Backend unavailable"}', { status: 503 });
  };
  const api = liveClient('csrf-token');
  await assert.rejects(() => api.guilds(), /Backend unavailable/);
  await assert.rejects(() => api.topics('123456789012345678'), /Backend unavailable/);
  assert.ok(calls[1].path.startsWith('/api/dashboard/guilds/123456789012345678/topics?'));
  assert.equal(calls[1].init.credentials, 'same-origin');
  assert.equal(calls[1].init.cache, 'no-store');
  assert.equal(await api.summary({ guild_id: '123456789012345678', topic_id: 't1' }), null);
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init });
    return new Response('{}');
  };
  await api.close({ guild_id: '123456789012345678', topic_id: 't1' });
  assert.equal(calls.at(-1).init.method, 'POST');
  assert.equal(calls.at(-1).init.headers['X-CSRF-Token'], 'csrf-token');
});
