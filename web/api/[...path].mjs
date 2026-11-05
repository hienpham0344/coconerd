import { createHandler } from '../server/handler.mjs';
import { environmentConfig, normalizeFunctionUrl } from '../server/config.mjs';

const handler = createHandler(environmentConfig());
export default async function dashboardApi(req, res) {
  try { req.url = normalizeFunctionUrl(req.url); }
  catch {
    res.writeHead(400, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ detail: 'Đường dẫn không hợp lệ.' })); return;
  }
  await handler(req, res);
}
