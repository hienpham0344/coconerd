export function isPrivatePath(pathname, dev) {
  const path = dev && pathname.startsWith('/node_modules/.vite/deps/')
    ? pathname.replace('/node_modules/.vite/deps/', '/bundled-dependencies/') : pathname;
  return path.split('/').some(segment => segment.startsWith('.')) || /^\/(server|bridge|tests|scripts|docs)(\/|$)/.test(path);
}
