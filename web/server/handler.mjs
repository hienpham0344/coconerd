function json(res, status, data, head = false) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(head ? undefined : JSON.stringify(data));
}

function discordLink(value, kind) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
    if (kind === 'invite') {
      if (url.hostname !== 'discord.com' || !['/oauth2/authorize', '/api/oauth2/authorize'].includes(url.pathname)) return null;
      if (!/^\d{15,22}$/.test(url.searchParams.get('client_id') || '')) return null;
    } else if (!(url.hostname === 'discord.gg' && /^\/[\w-]+\/?$/.test(url.pathname)) &&
               !(url.hostname === 'discord.com' && /^\/invite\/[\w-]+\/?$/.test(url.pathname))) return null;
    return url.href;
  } catch { return null; }
}

export function createHandler(config = {}, next) {
  const links = { inviteUrl: discordLink(config.inviteUrl, 'invite'), supportUrl: discordLink(config.supportUrl, 'support') };
  let cached;
  let pending;
  const health = async () => {
    if (cached && Date.now() - cached.at < 30_000) return cached.data;
    if (pending) return pending;
    pending = (async () => {
      const data = { status: 'unconfigured', database: 'unknown', worker: 'unknown', checkedAt: new Date().toISOString() };
      if (config.statusUrl) {
        data.status = 'unavailable';
        try {
          const url = new URL(config.statusUrl);
          if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid health URL');
          const response = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(5000), redirect: 'error' });
          const result = await response.json();
          const states = ['ok', 'unavailable', 'unknown'];
          if (!response.ok || !['ok', 'degraded'].includes(result.status) || !states.includes(result.database) || !states.includes(result.worker)) throw new Error('Invalid health response');
          data.database = result.database;
          data.worker = result.worker;
          data.status = result.status === 'ok' && result.database === 'ok' && result.worker === 'ok' ? 'ok' : 'degraded';
        } catch { /* An unavailable probe is a public status, never an invented uptime. */ }
      }
      cached = { at: Date.now(), data };
      return data;
    })();
    try { return await pending; } finally { pending = undefined; }
  };

  return async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'same-origin');
    res.setHeader('X-Frame-Options', 'DENY');
    let url;
    try { url = new URL(req.url, 'http://localhost'); }
    catch { return json(res, 400, { detail: 'Đường dẫn không hợp lệ.' }); }
    if (!url.pathname.startsWith('/api/')) return next ? next(req, res) : json(res, 404, { detail: 'Không tìm thấy trang.' });
    if (!['/api/site', '/api/status'].includes(url.pathname)) return json(res, 404, { detail: 'Không tìm thấy chức năng.' });
    if (!['GET', 'HEAD'].includes(req.method)) return json(res, 405, { detail: 'Chức năng này chỉ cho phép đọc.' });
    return json(res, 200, url.pathname === '/api/site' ? links : await health(), req.method === 'HEAD');
  };
}
