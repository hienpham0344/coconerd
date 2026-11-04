import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createHandler } from '../server/handler.mjs';
import { isPrivatePath } from '../server/assets.mjs';

async function serve(t, handler) {
  const server = createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  return `http://127.0.0.1:${server.address().port}`;
}

test('development dependencies load while private source and environment files stay private', () => {
  assert.equal(isPrivatePath('/node_modules/.vite/deps/react.js', true), false);
  for (const path of ['/.env', '/.env.local', '/server/index.mjs', '/bridge/app.py', '/.git/config', '/node_modules/.vite/deps/.env']) {
    assert.equal(isPrivatePath(path, true), true, path);
  }
  assert.equal(isPrivatePath('/node_modules/.vite/deps/react.js', false), true);
});

test('visitors get only public links without a session or secrets', async t => {
  const url = await serve(t, createHandler({ inviteUrl: 'https://discord.com/oauth2/authorize?client_id=123456789012345678&scope=bot', supportUrl: 'https://discord.gg/coconerd', password: 'private-password', botKey: 'private-key' }));
  const response = await fetch(`${url}/api/site`);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('set-cookie'), null);
  assert.deepEqual(await response.json(), { inviteUrl: 'https://discord.com/oauth2/authorize?client_id=123456789012345678&scope=bot', supportUrl: 'https://discord.gg/coconerd' });
});

test('missing or unsafe Discord URLs never create fake or unsafe invitations', async t => {
  for (const config of [{}, { inviteUrl: 'javascript:alert(1)', supportUrl: 'https://discord.gg.evil.example/test' }, { inviteUrl: 'https://discord.com@evil.example/oauth2/authorize', supportUrl: 'https://user:password@discord.gg/test' }]) {
    const url = await serve(t, createHandler(config));
    assert.deepEqual(await (await fetch(`${url}/api/site`)).json(), { inviteUrl: null, supportUrl: null });
  }
});

test('public website cannot log in, read private guild data, or mutate the backend', async t => {
  let upstreamRequests = 0;
  const upstream = await serve(t, (_req, res) => { upstreamRequests++; res.end('{}'); });
  const url = await serve(t, createHandler({ backendUrl: upstream, password: 'a-private-password', adminKey: 'private-key' }));
  for (const [method, path] of [['POST', '/api/login'], ['GET', '/api/session'], ['GET', '/api/backend/admin/web/guilds'], ['PUT', '/api/backend/admin/guilds/123/settings'], ['POST', '/api/backend/admin/topics/abc/close']]) {
    const response = await fetch(url + path, { method, headers: { cookie: `coconerd_session=${'a'.repeat(64)}` } });
    assert.equal(response.status, 404, path);
  }
  assert.equal(upstreamRequests, 0);
});

test('status remains unknown without a configured health source', async t => {
  const url = await serve(t, createHandler({}));
  const result = await (await fetch(`${url}/api/status`)).json();
  assert.equal(result.status, 'unconfigured');
  assert.equal(result.database, 'unknown');
  assert.equal(result.worker, 'unknown');
  assert.equal((await fetch(`${url}/api/status`, { method: 'POST' })).status, 405);
});

test('health responses expose only known states and cache requests; failures never claim uptime', async t => {
  for (const [body, expected] of [
    [{ status: 'ok', database: 'ok', worker: 'ok', private: 'never-expose-this' }, { status: 'ok', database: 'ok', worker: 'ok' }],
    [{ status: 'degraded', database: 'ok', worker: 'unavailable' }, { status: 'degraded', database: 'ok', worker: 'unavailable' }],
    [{ status: 'ok', database: 'secret-db-name', worker: 'unexpected' }, { status: 'unavailable', database: 'unknown', worker: 'unknown' }],
    ['not-json', { status: 'unavailable', database: 'unknown', worker: 'unknown' }],
  ]) {
    let count = 0;
    const upstream = await serve(t, (_req, res) => { count++; res.end(typeof body === 'string' ? body : JSON.stringify(body)); });
    const url = await serve(t, createHandler({ statusUrl: `${upstream}/api/v1/health` }));
    const result = await (await fetch(`${url}/api/status`)).json();
    assert.deepEqual({ status: result.status, database: result.database, worker: result.worker }, expected);
    assert.ok(!JSON.stringify(result).includes('never-expose-this'));
    await fetch(`${url}/api/status`);
    assert.equal(count, 1);
  }
});
