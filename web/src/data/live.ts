import { ApiError, client, request, type DashboardClient } from './api.ts';
import type { Guild, Message, Mode, Overview, Summary, Topic, TopicPage } from '../types';

export function clientForMode(mode: Mode, csrf = '', provided?: DashboardClient): DashboardClient {
  return provided || (mode === 'live' ? liveClient(csrf) : client());
}

export async function privateRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  try { return await request<T>(path, { ...init, credentials: 'same-origin', cache: 'no-store' }); }
  catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status) && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('coconerd-access-error', { detail: error.status }));
    }
    throw error;
  }
}

export function dashboardRequest<T>(guildId: string, resource: string, csrf: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  return privateRequest<T>('/api/dashboard/guilds/' + encodeURIComponent(guildId) + '/' + resource, {
    method,
    headers: method === 'GET' ? undefined : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });
}

export function liveClient(csrf: string): DashboardClient {
  const get = <T>(guild: string, resource: string, signal?: AbortSignal) => dashboardRequest<T>(guild, resource, csrf, 'GET', undefined, signal);
  return {
    guilds: async (signal?: AbortSignal) => (await privateRequest<{ items: Guild[] }>('/api/dashboard/guilds', signal ? { signal } : {})).items,
    overview: (guild: Guild, signal?: AbortSignal) => get<Overview>(guild.guild_id, 'overview', signal),
    topics: (guild, q = '', status = '', offset = 0, signal?: AbortSignal) => {
      const params = new URLSearchParams({ q, offset: String(offset), limit: '12' });
      if (status) params.set('status', status);
      return get<TopicPage>(guild, 'topics?' + params, signal);
    },
    topic: (guild, id, signal?: AbortSignal) => get<Topic>(guild, 'topics/' + encodeURIComponent(id), signal),
    messages: async (topic, before, signal?: AbortSignal) => {
      const params = new URLSearchParams({ limit: '50' }); if (before) params.set('before', before);
      return (await get<{ items: Message[] }>(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/messages?' + params, signal)).items;
    },
    summary: async (topic, signal?: AbortSignal) => {
      try { return await get<Summary>(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/summary', signal); }
      catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
    },
    close: async (topic, signal?: AbortSignal) => { await dashboardRequest(topic.guild_id, 'topics/' + encodeURIComponent(topic.topic_id) + '/close', csrf, 'POST', undefined, signal); },
  };
}
