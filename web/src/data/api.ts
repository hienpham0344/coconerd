import { demoGuilds, demoMessages, demoSummary, demoTopics } from './demo.ts';
import type { Guild, Message, Overview, Summary, Topic, TopicPage } from '../types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const signal = init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000);
  let response: Response;
  try { response = await fetch(path, { ...init, signal }); }
  catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(0, 'Chưa kết nối được website. Thử lại sau một chút nhé.');
  }
  if (response.status === 204) return undefined as T;
  let data: unknown;
  try { data = await response.json(); }
  catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(502, 'Chưa đọc được phản hồi từ website.');
  }
  const detail = data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string' ? (data as { detail: string }).detail : 'Chưa thể hoàn thành thao tác.';
  if (!response.ok) throw new ApiError(response.status, detail);
  return data as T;
}

function stored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(`coconerd-demo-${key}`) || 'null') ?? structuredClone(fallback); }
  catch { return structuredClone(fallback); }
}

export function resetDemo() {
  try { Object.keys(localStorage).filter(key => key.startsWith('coconerd-demo-')).forEach(key => localStorage.removeItem(key)); }
  catch { /* Ignore restricted storage in private browsing */ }
}

export function demoGuildForTopic(topicId?: string) {
  return stored('topics', demoTopics).find(topic => topic.topic_id === topicId)?.guild_id;
}

export interface DashboardClient {
  guilds(signal?: AbortSignal): Promise<Guild[]>;
  overview(guild: Guild, signal?: AbortSignal): Promise<Overview>;
  topics(guildId: string, query?: string, status?: string, offset?: number, signal?: AbortSignal): Promise<TopicPage>;
  topic(guildId: string, topicId: string, signal?: AbortSignal): Promise<Topic>;
  messages(topic: Topic, before?: string, signal?: AbortSignal): Promise<Message[]>;
  summary(topic: Topic, signal?: AbortSignal): Promise<Summary | null>;
  close(topic: Topic, signal?: AbortSignal): Promise<void>;
}

export function client(): DashboardClient {
  return {
    guilds: async (): Promise<Guild[]> => structuredClone(demoGuilds),
    overview: async (guild: Guild): Promise<Overview> => {
      const items = stored('topics', demoTopics).filter(topic => topic.guild_id === guild.guild_id);
      return { topics: items.length, active_topics: items.filter(topic => ['ACTIVE', 'RESUMED'].includes(topic.status)).length, messages: items.reduce((count, topic) => count + demoMessages(topic).length, 0), channels: guild.allowed_channel_ids.length };
    },
    topics: async (guildId: string, query = '', status = '', offset = 0): Promise<TopicPage> => {
      const items = stored('topics', demoTopics).filter(topic => topic.guild_id === guildId && (!status || topic.status === status) && topic.title.toLocaleLowerCase('vi').includes(query.toLocaleLowerCase('vi')));
      return { items: items.slice(offset, offset + 12).map(topic => ({ ...topic, message_count: demoMessages(topic).length })), total: items.length, limit: 12, offset };
    },
    topic: async (guildId: string, topicId: string): Promise<Topic> => {
      const topic = stored('topics', demoTopics).find(item => item.guild_id === guildId && item.topic_id === topicId);
      if (!topic) throw new ApiError(404, 'Không tìm thấy chủ đề trong không gian mẫu này.');
      return topic;
    },
    messages: async (topic: Topic, before?: string): Promise<Message[]> => before ? [] : demoMessages(topic),
    summary: async (topic: Topic): Promise<Summary> => demoSummary(topic),
    close: async (topic: Topic) => {
      const items = stored('topics', demoTopics).map(item => item.guild_id === topic.guild_id && item.topic_id === topic.topic_id ? { ...item, status: 'CLOSED' } : item);
      try { localStorage.setItem('coconerd-demo-topics', JSON.stringify(items)); }
      catch { throw new ApiError(0, 'Trình duyệt chưa cho phép lưu thay đổi của bản mẫu.'); }
    },
  };
}
