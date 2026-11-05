const aliases: Record<string, string> = {
  '/docs': '/guide', '/docs/setup': '/guide', '/docs/privacy': '/privacy',
  '/faq': '/guide', '/support': '/guide', '/status': '/guide', '/connect': '/invite',
};

export function resolveNavigation(hash: string, currentRoute = '/') {
  const requested = hash.replace(/^#/, '') || '/';
  const target = aliases[requested] || requested;
  if (target === '/invite') return { route: currentRoute, inviteOpen: true, resetScroll: false };
  return { route: target, inviteOpen: false, resetScroll: target !== currentRoute };
}
