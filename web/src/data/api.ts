import { demoGuilds, demoMessages, demoSummary, demoTopics } from './demo';
import type { Guild, Message, Overview, Summary, Topic, TopicPage } from '../types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(path, { ...init, signal: init.signal || AbortSignal.timeout(10_000) }); }
  catch { throw new ApiError(0, 'Unable to connect to the website. Please try again shortly.'); }
  let data;
  try { data = await response.json(); }
  catch { throw new ApiError(502, 'Unable to read response from the website.'); }
  if (!response.ok) throw new ApiError(response.status, typeof data.detail === 'string' ? data.detail : 'Unable to complete this action.');
  return data as T;
}

function stored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(`coconerd-demo-${key}`) || 'null') ?? structuredClone(fallback); }
  catch { return structuredClone(fallback); }
}

export function resetDemo() {
  Object.keys(localStorage).filter(key => key.startsWith('coconerd-demo-')).forEach(key => localStorage.removeItem(key));
}

export function demoGuildForTopic(topicId?: string) {
  return stored('topics', demoTopics).find(topic => topic.topic_id === topicId)?.guild_id;
}

export function client() {
  return {
    guilds: async (): Promise<Guild[]> => structuredClone(demoGuilds),
    overview: async (guild: Guild): Promise<Overview> => {
      const items = stored('topics', demoTopics).filter(topic => topic.guild_id === guild.guild_id);
      return { topics: items.length, active_topics: items.filter(topic => ['ACTIVE', 'RESUMED'].includes(topic.status)).length, messages: items.reduce((count, topic) => count + demoMessages(topic).length, 0), channels: guild.allowed_channel_ids.length };
    },
    topics: async (guildId: string, query = '', status = '', offset = 0): Promise<TopicPage> => {
      const items = stored('topics', demoTopics).filter(topic => topic.guild_id === guildId && (!status || topic.status === status) && topic.title.toLowerCase().includes(query.toLowerCase()));
      return { items: items.slice(offset, offset + 12).map(topic => ({ ...topic, message_count: demoMessages(topic).length })), total: items.length, limit: 12, offset };
    },
    topic: async (guildId: string, topicId: string): Promise<Topic> => {
      const topic = stored('topics', demoTopics).find(item => item.guild_id === guildId && item.topic_id === topicId);
      if (!topic) throw new ApiError(404, 'Topic not found in this demo workspace.');
      return topic;
    },
    messages: async (topic: Topic, before?: string): Promise<Message[]> => before ? [] : demoMessages(topic),
    summary: async (topic: Topic): Promise<Summary> => demoSummary(topic),
    close: async (topic: Topic) => {
      const items = stored('topics', demoTopics).map(item => item.guild_id === topic.guild_id && item.topic_id === topic.topic_id ? { ...item, status: 'CLOSED' } : item);
      try { localStorage.setItem('coconerd-demo-topics', JSON.stringify(items)); }
      catch { throw new ApiError(0, 'Browser storage is not permitted to save changes in this demo.'); }
    },
  };
}
