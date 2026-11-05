import { createCipheriv, createDecipheriv, createHash, randomBytes, timingSafeEqual } from 'node:crypto';

const API = 'https://discord.com/api/v10';
const TTL = 12 * 60 * 60 * 1000;
export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export const hash = value => createHash('sha256').update(value).digest('hex');
export const random = () => randomBytes(32).toString('base64url');
export function equal(a, b) {
  return typeof a === 'string' && typeof b === 'string' && Buffer.byteLength(a) === Buffer.byteLength(b) && timingSafeEqual(Buffer.from(a), Buffer.from(b));
}
export function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(status === 204 ? undefined : JSON.stringify(data));
}
export async function readBody(req) {
  if (!/^application\/json(?:;|$)/i.test(req.headers['content-type'] || '')) throw new HttpError(415, 'Cần gửi dữ liệu JSON.');
  let parsed;
  try { parsed = req.body; } catch { throw new HttpError(400, 'Dữ liệu JSON không hợp lệ.'); }
  if (parsed !== undefined) {
    let encoded;
    try { encoded = JSON.stringify(parsed); } catch { throw new HttpError(400, 'Dữ liệu JSON không hợp lệ.'); }
    if (Buffer.byteLength(encoded) > 1024 * 1024) throw new HttpError(413, 'Dữ liệu vượt giới hạn.');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new HttpError(400, 'Dữ liệu JSON không hợp lệ.');
    return parsed;
  }
  let size = 0; const chunks = [];
  for await (const chunk of req) {
    size += Buffer.byteLength(chunk);
    if (size > 1024 * 1024) throw new HttpError(413, 'Dữ liệu vượt giới hạn.');
    chunks.push(Buffer.from(chunk));
  }
  try {
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error();
    return body;
  } catch { throw new HttpError(400, 'Dữ liệu JSON không hợp lệ.'); }
}

export function createAuth(config) {
  const fetchImpl = config.fetchImpl || fetch;
  let origin, secure, key, backendOrigin;
  let enabled = false;
  try {
    const callback = new URL(config.redirectUri);
    const backend = new URL(config.backendUrl);
    secure = callback.protocol === 'https:';
    if (!secure && !(config.allowHttp === true && callback.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(callback.hostname))) throw new Error();
    if (callback.pathname !== '/auth/discord/callback' || callback.search || callback.hash || callback.username || callback.password) throw new Error();
    if (!['https:', 'http:'].includes(backend.protocol) || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash) throw new Error();
    if (!/^\d{15,22}$/.test(config.clientId) || !config.clientSecret || Buffer.byteLength(config.sessionSecret || '') < 32 || !config.adminKey || !config.botKey) throw new Error();
    key = createHash('sha256').update(config.sessionSecret).digest();
    origin = callback.origin; backendOrigin = backend.origin; enabled = true;
  } catch { /* Incomplete configuration denies access instead of weakening authentication. */ }
  const cookieName = secure ? '__Host-coconerd_session' : 'coconerd_session';
  const stateName = secure ? '__Host-coconerd_oauth' : 'coconerd_oauth';
  const cookie = (name, value, seconds) => name + '=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=' + seconds + (secure ? '; Secure' : '');
  const cookieValue = (req, name) => {
    const matches = (req.headers.cookie || '').split(';').map(p => p.trim()).filter(p => p.startsWith(name + '='));
    const value = matches.length === 1 ? matches[0].slice(name.length + 1) : '';
    return /^[A-Za-z0-9_-]{43}$/.test(value) ? value : null;
  };
  function seal(value, aad) {
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', key, iv);
    cipher.setAAD(Buffer.from(aad));
    const data = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final()]);
    return [iv, cipher.getAuthTag(), data].map(item => item.toString('base64url')).join('.');
  }
  function open(value, aad) {
    try {
      const parts = value.split('.').map(item => Buffer.from(item, 'base64url'));
      if (parts.length !== 3 || parts[0].length !== 12 || parts[1].length !== 16) throw new Error();
      const decipher = createDecipheriv('aes-256-gcm', key, parts[0]);
      decipher.setAAD(Buffer.from(aad)); decipher.setAuthTag(parts[1]);
      return JSON.parse(Buffer.concat([decipher.update(parts[2]), decipher.final()]).toString());
    } catch { throw new HttpError(401, 'Phiên đăng nhập không còn hợp lệ.'); }
  }
  async function fetchResponse(url, init = {}) {
    try { return await fetchImpl(url, { ...init, signal: AbortSignal.timeout(10000), redirect: 'error' }); }
    catch { throw new HttpError(503, 'Chưa kết nối được dịch vụ. Vui lòng thử lại.'); }
  }
  async function backend(path, { method = 'GET', body, bot = false, missing = false } = {}) {
    const headers = { Accept: 'application/json', [bot ? 'X-API-Key' : 'X-Admin-API-Key']: bot ? config.botKey : config.adminKey };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetchResponse(backendOrigin + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (missing && response.status === 404) return null;
    if (response.status === 204) return null;
    let data;
    try { data = await response.json(); } catch { throw new HttpError(502, 'Phản hồi backend không hợp lệ.'); }
    if (!response.ok) {
      const status = [400, 404, 409, 413, 422, 429].includes(response.status) ? response.status : 502;
      const detail = status !== 502 && typeof data.detail === 'string' ? data.detail : 'Backend chưa sẵn sàng hoặc từ chối yêu cầu.';
      throw new HttpError(status, detail);
    }
    return data;
  }
  const credentialPath = (kind, id) => '/api/v1/admin/web/credentials/' + kind + '/' + hash(id);
  async function store(kind, id, data, expiresAt, expectedPayload) {
    const path = credentialPath(kind, id);
    await backend(path, { method: 'PUT', body: { payload: seal(data, path), expires_at: new Date(expiresAt).toISOString(), ...(expectedPayload ? { expected_payload: expectedPayload } : {}) } });
  }
  async function stored(kind, id, consume = false) {
    const path = credentialPath(kind, id);
    const record = await backend(path + (consume ? '/consume' : ''), { method: consume ? 'POST' : 'GET', missing: true });
    if (!record || Date.parse(record.expires_at) <= Date.now()) return null;
    const data = open(record.payload, path);
    Object.defineProperty(data, 'storedPayload', { value: record.payload });
    return data;
  }
  async function discord(path, token, bot = false) {
    if (!token) throw new HttpError(503, 'Kết nối Discord chưa sẵn sàng.');
    const response = await fetchResponse(API + path, { headers: { Authorization: (bot ? 'Bot ' : 'Bearer ') + token, Accept: 'application/json' } });
    if (response.status === 401) throw new HttpError(401, 'Vui lòng đăng nhập lại bằng Discord.');
    if (!response.ok) throw new HttpError(503, 'Chưa xác minh được dữ liệu hoặc quyền Discord. Vui lòng thử lại.');
    try { return await response.json(); } catch { throw new HttpError(503, 'Phản hồi Discord không hợp lệ.'); }
  }
  async function token(form) {
    const response = await fetchResponse(API + '/oauth2/token', {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ client_id: config.clientId, client_secret: config.clientSecret, ...form }).toString(),
    });
    if (!response.ok) throw new HttpError(response.status >= 500 || response.status === 429 ? 503 : 401, 'Chưa đăng nhập được Discord. Vui lòng thử lại.');
    let data;
    try { data = await response.json(); } catch { throw new HttpError(503, 'Phản hồi đăng nhập không hợp lệ.'); }
    const scopes = new Set((data.scope || '').split(' '));
    if (data.token_type?.toLowerCase() !== 'bearer' || typeof data.access_token !== 'string' || !Number.isFinite(data.expires_in) || data.expires_in <= 0 || !scopes.has('identify') || !scopes.has('guilds')) throw new HttpError(401, 'Discord chưa cấp đủ quyền đăng nhập.');
    return { accessToken: data.access_token, refreshToken: data.refresh_token, tokenExpiresAt: Date.now() + data.expires_in * 1000 };
  }
  const refreshing = new Map();
  async function session(req) {
    const id = cookieValue(req, cookieName);
    if (!id) throw new HttpError(401, 'Vui lòng đăng nhập bằng Discord.');
    let data = await stored('session', id);
    if (!data || data.expiresAt <= Date.now()) throw new HttpError(401, 'Phiên đăng nhập đã hết hạn.');
    if (data.tokenExpiresAt <= Date.now() + 15000) {
      if (!refreshing.has(id)) refreshing.set(id, (async () => {
        const latest = await stored('session', id);
        if (!latest || latest.expiresAt <= Date.now()) throw new HttpError(401, 'Phiên đăng nhập đã hết hạn.');
        if (latest.tokenExpiresAt > Date.now() + 15000) return latest;
        if (!latest.refreshToken) throw new HttpError(401, 'Vui lòng đăng nhập lại bằng Discord.');
        const updated = { ...latest, ...await token({ grant_type: 'refresh_token', refresh_token: latest.refreshToken }) };
        if (!updated.refreshToken) updated.refreshToken = latest.refreshToken;
        try { await store('session', id, updated, updated.expiresAt, latest.storedPayload); }
        catch (error) {
          if (!(error instanceof HttpError) || error.status !== 409) throw error;
          const current = await stored('session', id);
          if (!current || current.tokenExpiresAt <= Date.now() + 15000) throw new HttpError(401, 'Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.');
          return current;
        }
        return updated;
      })().finally(() => refreshing.delete(id)));
      data = await refreshing.get(id);
    }
    return { id, ...data };
  }
  function csrf(req, data) {
    if (req.headers.origin !== origin || !equal(req.headers['x-csrf-token'], data.csrfToken)) throw new HttpError(403, 'Yêu cầu xác nhận không hợp lệ. Vui lòng tải lại trang.');
  }
  const guildCache = new Map();
  async function guilds(data, fresh = false) {
    const cached = guildCache.get(hash(data.id));
    if (!fresh && cached && cached.until > Date.now()) return cached.items;
    try {
    const items = []; let after = '';
    for (let page = 0; page < 10; page++) {
      const batch = await discord('/users/@me/guilds?limit=200' + (after ? '&after=' + after : ''), data.accessToken);
      if (!Array.isArray(batch)) throw new HttpError(503, 'Chưa đọc được quyền Discord.');
      for (const g of batch) {
        if (!/^\d{15,22}$/.test(g.id)) continue;
        const admin = /^\d+$/.test(g.permissions || '') && (BigInt(g.permissions) & 8n) !== 0n;
        if (g.owner === true || admin) items.push({ id: g.id, name: String(g.name || g.id) });
      }
      if (batch.length < 200) {
        if (guildCache.size > 2000) guildCache.clear();
        guildCache.set(hash(data.id), { items, until: Date.now() + 30000 });
        return items;
      }
      const next = batch.at(-1)?.id;
      if (!/^\d{15,22}$/.test(next) || next === after) break;
      after = next;
    }
    throw new HttpError(503, 'Chưa đọc đầy đủ quyền Discord.');
    } catch (error) { guildCache.delete(hash(data.id)); throw error; }
  }
  async function channels(guild) {
    const items = await discord('/guilds/' + guild + '/channels', config.discordBotToken, true);
    if (!Array.isArray(items)) throw new HttpError(503, 'Chưa đọc được danh sách kênh.');
    return items.filter(item => [0, 5].includes(item.type) && /^\d{15,22}$/.test(item.id) && (!item.guild_id || item.guild_id === guild)).map(item => ({ id: item.id, name: String(item.name), type: item.type }));
  }
  async function start(req, res) {
    const state = random(); const verifier = random();
    await store('oauth', state, { verifier }, Date.now() + 5 * 60 * 1000);
    const target = new URL('https://discord.com/oauth2/authorize');
    target.search = new URLSearchParams({ client_id: config.clientId, redirect_uri: config.redirectUri, response_type: 'code', scope: 'identify guilds', state, code_challenge: createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256' }).toString();
    res.writeHead(302, { Location: target.href, 'Set-Cookie': cookie(stateName, state, 300) }); res.end();
  }
  async function callback(req, res, url) {
    const state = url.searchParams.get('state');
    if (url.searchParams.getAll('state').length !== 1 || url.searchParams.getAll('code').length !== 1 || !equal(state, cookieValue(req, stateName)) || url.searchParams.get('iss') !== 'https://discord.com') throw new HttpError(400, 'Yêu cầu đăng nhập đã hết hạn hoặc không hợp lệ.');
    const saved = await stored('oauth', state, true);
    if (!saved) throw new HttpError(400, 'Yêu cầu đăng nhập đã được dùng hoặc hết hạn.');
    const tokens = await token({ grant_type: 'authorization_code', code: url.searchParams.get('code'), redirect_uri: config.redirectUri, code_verifier: saved.verifier });
    const user = await discord('/users/@me', tokens.accessToken);
    if (!/^\d{15,22}$/.test(user.id) || typeof user.username !== 'string') throw new HttpError(401, 'Danh tính Discord không hợp lệ.');
    const old = cookieValue(req, cookieName);
    if (old) await backend(credentialPath('session', old), { method: 'DELETE' });
    const id = random();
    const data = { ...tokens, user: { id: user.id, username: user.username, displayName: user.global_name || user.username }, csrfToken: random(), expiresAt: Date.now() + TTL };
    await store('session', id, data, data.expiresAt);
    res.writeHead(302, { Location: '/#/app', 'Set-Cookie': [cookie(cookieName, id, TTL / 1000), cookie(stateName, '', 0)] }); res.end();
  }
  async function logout(req, res, data) {
    csrf(req, data);
    await backend(credentialPath('session', data.id), { method: 'DELETE' });
    guildCache.delete(hash(data.id));
    res.setHeader('Set-Cookie', cookie(cookieName, '', 0)); json(res, 204);
  }
  return { enabled, backend, session, csrf, guilds, channels, start, callback, logout, cookie, cookieName };
}
