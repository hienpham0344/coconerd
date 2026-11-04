import { createHandler } from '../server/handler.mjs';

const handler = createHandler({
  inviteUrl: process.env.DISCORD_INVITE_URL,
  supportUrl: process.env.DISCORD_SUPPORT_URL,
  statusUrl: process.env.COCONERD_STATUS_URL,
});

export default async function site(req, res) {
  const original = req.url || '/api/site';
  const qIndex = original.indexOf('?');
  const query = qIndex !== -1 ? original.slice(qIndex) : '';
  req.url = `/api/site${query}`;
  return handler(req, res);
}
