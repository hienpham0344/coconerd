import { ApiError, request, type DashboardClient } from './api.ts';
import type { Guild, Message, Overview, Summary, Topic, TopicPage } from '../types';

export async function privateRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  try { return await request<T>(path, { ...init, credentials: 'same-origin', cache: 'no-store' }); }
  catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status) && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('coconerd-access-error', { detail: error.status }));
    }
    throw error;
  }
}

export function dashboardRequest<T>(guildId: string, resource: string, csrf: string, method = 'GET', body?: unknown): Promise<T> {
  return privateRequest<T>('/api/dashboard/guilds/' + encodeURIComponent(guildId) + '/' + resource, {
    method,
    headers: method === 'GET' ? undefined : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function liveClient(csrf: string): DashboardClient {
  const get = <T>(guild: string, resource: string) => dashboardRequest<T>(guild, resource, csrf);
  return {
    guilds: async () => (await privateRequest<{ items: Guild[] }>('/api/dashboard/guilds')).items,
    overview: (guild: Guild) => get<Overview>(guild.guild_id, 'overview'),
    topics: (guild, q = '', status = '', offset = 0) => {
      const params = new URLSearchParams({ q, offset: String(offset), limit: '12' });
      if (status) params.set('status', status);
      return get<TopicPage>(guild, 'topics?' + params);
    },
    topic: (guild, id) => get<Topic>(guild, 'topics/' + encodeURIComponent(id)),
    messages: async (topic, before) => {
      const params = new URLSearchParams({ limit: '50' }); if (before) params.set('before', before);
      return (await get<{ items: Message[] }>(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/messages?' + params)).items;
    },
    summary: async topic => {
      try { return await get<Summary>(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/summary'); }
      catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
    },
    close: async topic => { await dashboardRequest(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/close', csrf, 'POST'); },
  };
}
