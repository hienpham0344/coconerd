import { createHandler } from '../server/handler.mjs';
import { environmentConfig, normalizeFunctionUrl } from '../server/config.mjs';

const handler = createHandler(environmentConfig());
export default async function dashboardApi(req, res) {
  try { req.url = normalizeFunctionUrl(req.url); }
  catch {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'same-origin');
    res.setHeader('X-Frame-Options', 'DENY');
    res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ detail: 'Đường dẫn không hợp lệ.' })); return;
  }
  await handler(req, res);
}
