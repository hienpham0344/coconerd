import { createAuth, HttpError, json, readBody } from './auth.mjs';

export function createDashboardHandler(config = {}) {
  const auth = createAuth(config);
  const rates = new Map();
  function rate(key, limit) {
    const now = Date.now();
    if (rates.size > 5000) for (const [id, item] of rates) if (item.until <= now) rates.delete(id);
    const record = rates.get(key);
    if (!record || record.until <= now) rates.set(key, { count: 1, until: now + 60000 });
    else if (++record.count > limit) throw new HttpError(429, 'Quá nhiều yêu cầu. Vui lòng thử lại sau một phút.');
  }
  function query(url, allowed) {
    for (const key of url.searchParams.keys()) {
      if (!allowed.includes(key) || url.searchParams.getAll(key).length !== 1) throw new HttpError(400, 'Tham số không hợp lệ.');
    }
    return new URLSearchParams(url.searchParams);
  }
  return async (req, res, url) => {
    if (!/^\/(?:auth(?:\/|$)|api\/(?:auth|dashboard)(?:\/|$))/.test(url.pathname)) return false;
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
    try {
      if (!auth.enabled) throw new HttpError(503, 'Đăng nhập quản trị chưa sẵn sàng.');
      if (req.url.length > 8192) throw new HttpError(414, 'Đường dẫn quá dài.');
      if (url.pathname === '/auth/discord' || url.pathname === '/auth/discord/callback') {
        if (req.method !== 'GET') throw new HttpError(405, 'Phương thức không được hỗ trợ.');
        rate('login:' + req.socket?.remoteAddress, 30);
        if (url.pathname === '/auth/discord') { query(url, []); await auth.start(req, res); }
        else await auth.callback(req, res, url);
        return true;
      }
      const data = await auth.session(req);
      rate('session:' + data.id, 180);
      const write = !['GET', 'HEAD'].includes(req.method);
      if (write) auth.csrf(req, data);
      if (url.pathname === '/api/auth/session' && req.method === 'GET') {
        query(url, []);
        json(res, 200, { user: data.user, csrfToken: data.csrfToken, expiresAt: new Date(data.expiresAt).toISOString() });
        return true;
      }
      if (url.pathname === '/api/auth/logout' && req.method === 'POST') {
        query(url, []); await auth.logout(req, res, data); return true;
      }
      if (url.pathname === '/api/dashboard/guilds' && req.method === 'GET') {
        query(url, []);
        const permissions = new Map((await auth.guilds(data)).map(g => [g.id, g]));
        const items = [];
        for (let offset = 0; ; offset += 200) {
          const result = await auth.backend('/api/v1/admin/web/guilds?limit=200&offset=' + offset);
          for (const guild of result.items) if (permissions.has(guild.guild_id)) items.push({ ...guild, name: permissions.get(guild.guild_id).name });
          if (result.items.length < 200) break;
          if (offset > 100000) throw new HttpError(503, 'Chưa tải đủ danh sách server.');
        }
        json(res, 200, { items }); return true;
      }
      const match = url.pathname.match(/^\/api\/dashboard\/guilds\/(\d{15,22})\/(.+)$/);
      if (!match) throw new HttpError(404, 'Không tìm thấy chức năng.');
      const [, guild, resource] = match;
      if (!(await auth.guilds(data, write)).some(g => g.id === guild)) throw new HttpError(403, 'Bạn không còn quyền quản trị server này.');
      const base = '/api/v1/admin/web/guilds/' + guild;
      const guildBase = '/api/v1/guilds/' + guild;
      let path, params = new URLSearchParams(), bot = false, body;
      if (resource === 'channels' && req.method === 'GET') {
        query(url, []); json(res, 200, { items: await auth.channels(guild) }); return true;
      }
      if (resource === 'overview' && req.method === 'GET') { query(url, []); path = base + '/overview'; }
      else if (resource === 'topics' && req.method === 'GET') {
        params = query(url, ['q', 'status', 'limit', 'offset']); path = base + '/topics';
      } else if (resource === 'settings' && ['GET', 'PUT'].includes(req.method)) {
        query(url, []);
        path = req.method === 'GET' ? base + '/settings' : '/api/v1/admin/guilds/' + guild + '/settings';
        if (write) {
          body = await readBody(req);
          if (Object.keys(body).some(k => !['enabled', 'allowed_channel_ids', 'retention_days', 'output_channel_id'].includes(k)) || !Array.isArray(body.allowed_channel_ids)) throw new HttpError(422, 'Cấu hình server không hợp lệ.');
          const valid = new Set((await auth.channels(guild)).map(c => c.id));
          const ids = [...body.allowed_channel_ids, ...(body.output_channel_id ? [body.output_channel_id] : [])];
          if (ids.some(id => !valid.has(id))) throw new HttpError(422, 'Kênh phải thuộc server đang quản trị.');
        }
      } else if (resource === 'model' && ['GET', 'PUT'].includes(req.method)) {
        query(url, []); path = '/api/v1/admin/model-config'; params.set('guild_id', guild);
        if (write) body = await readBody(req);
      } else {
        const topic = resource.match(/^topics\/([A-Za-z0-9_-]{1,100})(?:\/(messages|summary|close|sync|resume-sync))?$/);
        const message = resource.match(/^messages\/([A-Za-z0-9_-]{1,100})\/(review|corrections)$/);
        const action = resource.match(/^actions\/([A-Za-z0-9_-]{1,100})\/recover$/);
        if (topic) {
          const [, id, operation] = topic;
          if ((!operation || ['messages', 'summary'].includes(operation)) && req.method === 'GET') {
            params = query(url, operation === 'messages' ? ['before', 'limit'] : []);
            params.set('guild_id', guild); bot = true;
            path = '/api/v1/topics/' + id + (operation ? '/' + operation : '');
          } else if (operation === 'close' && req.method === 'POST') {
            query(url, []); params.set('guild_id', guild); path = '/api/v1/admin/topics/' + id + '/close';
          } else if (operation === 'sync' && req.method === 'GET') {
            params = query(url, ['limit', 'offset']); path = guildBase + '/topics/' + id + '/sync';
          } else if (operation === 'resume-sync' && req.method === 'POST') {
            query(url, []); path = guildBase + '/topics/' + id + '/resume-sync'; body = await readBody(req);
          }
        } else if (message && ((message[2] === 'review' && req.method === 'GET') || (message[2] === 'corrections' && req.method === 'POST'))) {
          query(url, []); path = guildBase + '/messages/' + message[1] + '/' + message[2];
          if (write) body = await readBody(req);
        } else if (action && req.method === 'POST') {
          query(url, []); path = guildBase + '/actions/' + action[1] + '/recover'; body = await readBody(req);
        }
        if (body) body.actor = 'discord:' + data.user.id;
      }
      if (!path) throw new HttpError(404, 'Không tìm thấy chức năng.');
      const result = await auth.backend(path + (params.size ? '?' + params : ''), { method: req.method, body, bot });
      json(res, 200, result);
    } catch (error) {
      if (error.status === 401) res.setHeader('Set-Cookie', auth.cookie(auth.cookieName, '', 0));
      json(res, error instanceof HttpError ? error.status : 503, { detail: error instanceof HttpError ? error.message : 'Chức năng quản trị tạm thời chưa sẵn sàng.' });
    }
    return true;
  };
}
