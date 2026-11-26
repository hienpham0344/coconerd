export function isPrivatePath(pathname, dev) {
  if (typeof pathname !== 'string' || pathname.includes('\0') || pathname.includes('\\')) return true;
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch { return true; }
  if (decoded.includes('\0') || decoded.includes('\\')) return true;
  const normalized = decoded.replace(/\/+/g, '/');
  const path = dev && normalized.startsWith('/node_modules/.vite/deps/')
    ? normalized.replace('/node_modules/.vite/deps/', '/bundled-dependencies/') : normalized;
  return path.split('/').some(segment => segment.startsWith('.')) || /^\/(server|api|bridge|tests|scripts|docs)(\/|$)/i.test(path);
}
