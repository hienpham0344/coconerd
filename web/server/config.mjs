export function environmentConfig(env = process.env) {
  return {
    inviteUrl: env.DISCORD_INVITE_URL,
    supportUrl: env.DISCORD_SUPPORT_URL,
    statusUrl: env.COCONERD_STATUS_URL,
    clientId: env.DISCORD_CLIENT_ID,
    clientSecret: env.DISCORD_CLIENT_SECRET,
    redirectUri: env.DISCORD_REDIRECT_URI,
    sessionSecret: env.DASHBOARD_SESSION_SECRET,
    backendUrl: env.BACKEND_BASE_URL,
    botKey: env.COCONERD_BOT_API_KEY,
    adminKey: env.COCONERD_ADMIN_API_KEY,
    discordBotToken: env.DISCORD_BOT_TOKEN,
    allowHttp: env.COCONERD_WEB_ALLOW_HTTP === 'true',
  };
}

export function normalizeFunctionUrl(value) {
  const url = new URL(value, 'http://localhost');
  if (['/api/auth/discord', '/api/auth/discord/callback'].includes(url.pathname)) {
    return url.pathname.slice(4) + url.search;
  }
  return url.pathname + url.search;
}
