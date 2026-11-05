import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHandler } from './handler.mjs';
import { environmentConfig } from './config.mjs';
import { isPrivatePath } from './assets.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dev = process.argv.includes('--dev');
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || 5173);
const server = createServer();
const vite = dev ? await (await import('vite')).createServer({ root, server: { middlewareMode: true, hmr: { server } }, appType: 'spa' }) : null;
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2', '.json': 'application/json' };

async function staticHandler(req, res) {
  let pathname;
  try { pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname); } catch { res.writeHead(400).end(); return; }
  if (isPrivatePath(pathname, dev)) { res.writeHead(404).end(); return; }
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405).end(); return; }
  if (vite) return vite.middlewares(req, res);
  const dist = path.join(root, 'dist');
  let filename = path.resolve(dist, `.${pathname}`);
  if (!filename.startsWith(`${dist}${path.sep}`) && filename !== dist) { res.writeHead(404).end(); return; }
  try {
    const info = await stat(filename).catch(() => null);
    if (!info?.isFile()) {
      if (path.extname(pathname)) { res.writeHead(404).end(); return; }
      filename = path.join(dist, 'index.html');
    }
    const data = await readFile(filename);
    res.writeHead(200, { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream', 'Cache-Control': pathname.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache' });
    res.end(req.method === 'HEAD' ? undefined : data);
  } catch { res.writeHead(503).end('Build the website first: npm run build'); }
}

server.on('request', createHandler(environmentConfig(), staticHandler));
server.listen(port, host, () => console.log(`Coconerd: http://${host}:${port}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, async () => {
  server.close();
  server.closeAllConnections();
  await vite?.close();
  process.exit(0);
});
