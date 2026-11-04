export type Mode = 'demo';
export type TopicStatus = 'ACTIVE' | 'RESUMED' | 'DORMANT' | 'CLOSED';
export interface Guild { guild_id: string; enabled: boolean; allowed_channel_ids: string[]; retention_days: number; name?: string }
export interface Topic { topic_id: string; guild_id: string; title: string; description: string; status: TopicStatus; last_activity: string; discord_thread_id: string | null; message_count?: number }
export interface Message { message_id: string; channel_id: string; author_id: string; author_name: string; content: string; created_at: string; reply_to_message_id?: string | null }
export interface ModelConfig { provider: 'meta'; model_id: string; temperature: number; max_tokens: number; scope?: string; guild_id?: string | null }
export interface Overview { topics: number; active_topics: number; messages: number; channels: number }
export interface TopicPage { items: Topic[]; total: number; limit: number; offset: number }
export interface Summary { version: number; source_message_ids: string[]; [key: string]: unknown }
export interface SiteConfig { inviteUrl: string | null; supportUrl: string | null }
export interface PublicStatus {
  status: 'ok' | 'degraded' | 'unavailable' | 'unconfigured';
  database: 'ok' | 'unavailable' | 'unknown';
  worker: 'ok' | 'unavailable' | 'unknown';
  checkedAt: string;
}
