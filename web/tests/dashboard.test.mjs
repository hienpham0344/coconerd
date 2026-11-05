import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { createHash } from 'node:crypto';
import { createHandler } from '../server/handler.mjs';

const GUILD = '123456789012345678';
const OTHER = '223456789012345678';
function fixture() {
  const credentials = new Map(); const calls = [];
  const state = { guilds: [{ id: GUILD, name: 'Garden', owner: true, permissions: '0' }], discordDown: false, tokenSeconds: 3600 };
  const json = (data, status = 200) => new Response(status === 204 ? null : JSON.stringify(data), { status });
  const config = {
    clientId: GUILD, clientSecret: 'discord-client-secret', sessionSecret: 'test-encryption-key-at-least-32-characters',
    redirectUri: 'https://app.test/auth/discord/callback', backendUrl: 'https://backend.test',
    adminKey: 'backend-admin-secret', botKey: 'backend-bot-secret', discordBotToken: 'discord-bot-secret',
    fetchImpl: async (input, init = {}) => {
      const url = new URL(input); calls.push({ url, init });
      if (url.host === 'discord.com') {
        if (state.discordDown) return json({}, 503);
        if (url.pathname.endsWith('/oauth2/token')) {
          const body = new URLSearchParams(init.body);
          assert.equal(body.get('client_secret'), config.clientSecret);
          assert.ok(body.get('code_verifier') || body.get('refresh_token'));
          if (body.get('grant_type') === 'refresh_token') await state.beforeRefresh?.();
          return json({ access_token: 'discord-access-secret', refresh_token: 'discord-refresh-secret', token_type: 'Bearer', scope: 'identify guilds', expires_in: state.tokenSeconds });
        }
        if (url.pathname.endsWith('/users/@me')) return json({ id: '323456789012345678', username: 'hien', global_name: 'Hien', avatar: null });
        if (url.pathname.endsWith('/users/@me/guilds')) return json(state.guilds);
        if (url.pathname.endsWith('/channels')) return json([{ id: '423456789012345678', guild_id: GUILD, name: 'general', type: 0 }]);
        return json({}, 404);
      }
      assert.equal(url.host, 'backend.test', 'no arbitrary upstream');
      const headers = new Headers(init.headers);
      assert.ok(headers.get('X-Admin-API-Key') === config.adminKey || headers.get('X-API-Key') === config.botKey);
      if (url.pathname.includes('/credentials/')) {
        const key = url.pathname.replace(/\/consume$/, '');
        if (init.method === 'PUT') {
          const body = JSON.parse(init.body);
          if (body.expected_payload && credentials.get(key)?.payload !== body.expected_payload) return json({ detail: 'Credential changed or revoked' }, 409);
          credentials.set(key, body); return json({ status: 'saved' });
        }
        const record = credentials.get(key);
        if (init.method === 'DELETE') { credentials.delete(key); return json(null, 204); }
        if (!record || Date.parse(record.expires_at) < Date.now()) return json({}, 404);
        if (init.method === 'POST') credentials.delete(key);
        return json(record);
      }
      if (url.pathname === '/api/v1/admin/web/guilds') return json({ items: [{ guild_id: GUILD, enabled: true, allowed_channel_ids: [] }, { guild_id: OTHER, enabled: true, allowed_channel_ids: [] }] });
      if (url.pathname.endsWith('/corrections')) return json(JSON.parse(init.body));
      if (url.pathname.endsWith('/settings')) return json({ guild_id: GUILD, enabled: true, allowed_channel_ids: [] });
      if (url.pathname.includes('/topics/foreign')) return json({ detail: 'Topic not found' }, 404);
      return json({ topics: 2, active_topics: 1, messages: 5, channels: 1 });
    },
  };
  return { config, state, credentials, calls, handler: createHandler(config) };
}

async function request(handler, path, { method = 'GET', cookie, csrf, origin, body } = {}) {
  const req = Readable.from(body ? [JSON.stringify(body)] : []);
  Object.assign(req, { url: path, method, headers: {}, socket: { remoteAddress: '127.0.0.1' } });
  if (cookie) req.headers.cookie = cookie;
  if (csrf) req.headers['x-csrf-token'] = csrf;
  if (origin) req.headers.origin = origin;
  if (body) req.headers['content-type'] = 'application/json';
  const result = { status: 200, headers: {}, text: '' };
  const res = {
    setHeader(key, value) { result.headers[key.toLowerCase()] = value; },
    writeHead(status, headers = {}) { result.status = status; for (const [key, value] of Object.entries(headers)) this.setHeader(key, value); return this; },
    end(body) { result.text = body?.toString() || ''; },
  };
  await handler(req, res);
  result.json = () => JSON.parse(result.text);
  return result;
}

async function login(f) {
  const start = await request(f.handler, '/auth/discord');
  assert.equal(start.status, 302);
  const target = new URL(start.headers.location);
  assert.equal(target.searchParams.get('scope'), 'identify guilds');
  assert.equal(target.searchParams.get('code_challenge_method'), 'S256');
  assert.ok(target.searchParams.get('code_challenge'));
  const state = target.searchParams.get('state');
  const stateCookie = [].concat(start.headers['set-cookie'])[0].split(';')[0];
  const callback = `/auth/discord/callback?code=test-code&state=${state}&iss=https%3A%2F%2Fdiscord.com`;
  const done = await request(f.handler, callback, { cookie: stateCookie });
  assert.equal(done.status, 302, done.text);
  const cookies = [].concat(done.headers['set-cookie']).join(';');
  assert.ok(cookies.includes('HttpOnly') && cookies.includes('Secure') && cookies.includes('SameSite=Lax'));
  assert.ok(cookies.includes('Max-Age=43200'));
  assert.ok(!cookies.includes('Domain='));
  const sessionCookie = [].concat(done.headers['set-cookie']).find(value => value.startsWith('__Host-coconerd_session=')).split(';')[0];
  const session = await request(f.handler, '/api/auth/session', { cookie: sessionCookie });
  assert.equal(session.status, 200);
  return { cookie: sessionCookie, csrf: session.json().csrfToken, stateCookie, callback };
}

test('OAuth state, PKCE, encrypted persistence, replay protection and shared sessions', async () => {
  const f = fixture(); const auth = await login(f);
  assert.ok(!JSON.stringify([...f.credentials.values()]).includes('discord-access-secret'));
  const info = await request(createHandler(f.config), '/api/auth/session', auth);
  assert.equal(info.status, 200);
  assert.equal(info.json().user.username, 'hien');
  assert.ok(!info.text.includes('secret'));
  assert.equal((await request(f.handler, auth.callback, { cookie: auth.stateCookie })).status, 400);
  assert.equal((await request(f.handler, '/auth/discord/callback?code=bad&state=wrong')).status, 400);
  const storedKey = createHash('sha256').update(auth.cookie.split('=')[1]).digest('hex');
  assert.ok([...f.credentials.keys()].some(key => key.endsWith(storedKey)));
});

test('private dashboard requires login and returns only configured guilds the user administers', async () => {
  const f = fixture();
  assert.equal((await request(f.handler, '/api/dashboard/guilds')).status, 401);
  const auth = await login(f);
  const list = await request(f.handler, '/api/dashboard/guilds', auth);
  assert.deepEqual(list.json().items.map(g => g.guild_id), [GUILD]);
  assert.equal((await request(f.handler, `/api/dashboard/guilds/${OTHER}/overview`, auth)).status, 403);
  assert.equal((await request(f.handler, `/api/dashboard/guilds/${GUILD}/topics/foreign`, auth)).status, 404);
});

test('mutations require CSRF, same origin, current admin permission and server-owned actor', async () => {
  const f = fixture(); const auth = await login(f);
  const path = `/api/dashboard/guilds/${GUILD}/messages/message-1/corrections`;
  const write = { ...auth, method: 'POST', origin: 'https://app.test', body: { actor: 'forged', expected_revision: 0, target_topic_id: null, summaries: [], reason: 'fix', request_id: 'request-1' } };
  assert.equal((await request(f.handler, path, { ...write, csrf: undefined })).status, 403);
  assert.equal((await request(f.handler, path, { ...write, origin: 'https://evil.test' })).status, 403);
  const result = await request(f.handler, path, write);
  assert.equal(result.status, 200);
  assert.equal(result.json().actor, 'discord:323456789012345678');
  f.state.guilds = [{ id: GUILD, owner: false, permissions: '32' }];
  assert.equal((await request(f.handler, path, write)).status, 403, 'Manage Guild cannot read private conversations');
  f.state.guilds = [{ id: GUILD, owner: false, permissions: '8' }];
  assert.equal((await request(f.handler, path, write)).status, 200);
  f.state.discordDown = true;
  assert.equal((await request(f.handler, path, write)).status, 503);
});

test('no arbitrary proxy/global model/channel escalation; logout revokes server session', async () => {
  const f = fixture(); const auth = await login(f);
  for (const path of ['/api/dashboard/model-config', '/api/dashboard/credentials/session/key', `/api/dashboard/guilds/${GUILD}/topics/a/../../model-config`, `/api/dashboard/guilds/${GUILD}/model?guild_id=${OTHER}`]) {
    assert.ok([400, 404].includes((await request(f.handler, path, auth)).status), path);
  }
  const settings = await request(f.handler, `/api/dashboard/guilds/${GUILD}/settings`, { ...auth, method: 'PUT', origin: 'https://app.test', body: { enabled: true, retention_days: 30, allowed_channel_ids: ['999999999999999999'], output_channel_id: null } });
  assert.equal(settings.status, 422);
  assert.equal((await request(f.handler, '/api/auth/logout', { ...auth, method: 'POST', origin: 'https://app.test' })).status, 204);
  assert.equal((await request(f.handler, '/api/auth/session', auth)).status, 401);
});

test('failed fresh permission check invalidates earlier cached read permission', async () => {
  const f = fixture(); const auth = await login(f);
  const path = '/api/dashboard/guilds/' + GUILD + '/overview';
  assert.equal((await request(f.handler, path, auth)).status, 200);
  f.state.discordDown = true;
  const write = await request(f.handler, '/api/dashboard/guilds/' + GUILD + '/topics/t1/close', { ...auth, method: 'POST', origin: 'https://app.test' });
  assert.equal(write.status, 503);
  assert.equal((await request(f.handler, path, auth)).status, 503);
});

test('expired/tampered sessions and incomplete configuration never return private data', async () => {
  const f = fixture(); const auth = await login(f);
  const key = [...f.credentials.keys()].find(key => key.includes('/session/'));
  const record = f.credentials.get(key);
  record.expires_at = new Date(Date.now() - 1000).toISOString();
  assert.equal((await request(f.handler, '/api/auth/session', auth)).status, 401);
  record.expires_at = new Date(Date.now() + 60000).toISOString();
  record.payload = 'tampered-value';
  assert.equal((await request(f.handler, '/api/auth/session', auth)).status, 401);
  const broken = createHandler({ ...f.config, sessionSecret: 'too-short' });
  assert.equal((await request(broken, '/auth/discord')).status, 503);
});

test('refresh cannot recreate a session concurrently revoked by logout', async () => {
  const f = fixture(); f.state.tokenSeconds = 1;
  const auth = await login(f);
  const key = [...f.credentials.keys()].find(key => key.includes('/session/'));
  f.state.beforeRefresh = () => f.credentials.delete(key);
  assert.equal((await request(f.handler, '/api/auth/session', auth)).status, 401);
  assert.equal(f.credentials.has(key), false);
});
