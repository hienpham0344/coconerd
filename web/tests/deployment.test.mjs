import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { environmentConfig, normalizeFunctionUrl } from '../server/config.mjs';
import { readBody } from '../server/auth.mjs';

test('serverless OAuth rewrites preserve query and runtime secrets stay server configuration', () => {
  assert.equal(normalizeFunctionUrl('/api/auth/discord/callback?code=abc&state=def&iss=https%3A%2F%2Fdiscord.com'), '/auth/discord/callback?code=abc&state=def&iss=https%3A%2F%2Fdiscord.com');
  assert.equal(normalizeFunctionUrl('/api/auth/session'), '/api/auth/session');
  assert.equal(normalizeFunctionUrl('/api/dashboard/guilds'), '/api/dashboard/guilds');
  const config = environmentConfig({ DISCORD_CLIENT_ID: 'id', DISCORD_CLIENT_SECRET: 'server-only', DASHBOARD_SESSION_SECRET: 'encryption', COCONERD_WEB_ALLOW_HTTP: 'true' });
  assert.equal(config.clientSecret, 'server-only');
  assert.equal(config.allowHttp, true);
  assert.equal(environmentConfig({}).allowHttp, false);
});

test('serverless parsed JSON is bounded and validated like a streamed request', async () => {
  const req = Readable.from([]);
  req.headers = { 'content-type': 'application/json' };
  req.body = { reason: 'verified' };
  assert.deepEqual(await readBody(req), { reason: 'verified' });
  req.body = ['invalid'];
  await assert.rejects(() => readBody(req), /không hợp lệ/);
  req.body = { value: 'x'.repeat(1024 * 1024 + 1) };
  await assert.rejects(() => readBody(req), /giới hạn/);
});
