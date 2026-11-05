export type Mode = 'demo' | 'live';
export type TopicStatus = 'ACTIVE' | 'RESUMED' | 'DORMANT' | 'CLOSED';
export interface Guild { guild_id: string; enabled: boolean; allowed_channel_ids: string[]; retention_days: number; output_channel_id?: string | null; name?: string }
export interface Topic { topic_id: string; guild_id: string; title: string; description: string; status: TopicStatus; last_activity: string; discord_thread_id: string | null; message_count?: number }
export interface Message { message_id: string; channel_id: string; author_id: string; author_name: string; content: string; created_at: string; reply_to_message_id?: string | null; attachments?: { filename?: string; url?: string }[] }
export interface ModelConfig { provider: 'meta'; model_id: string; temperature: number; max_tokens: number; scope?: string; guild_id?: string | null }
export interface Overview { topics: number; active_topics: number; messages: number; channels: number }
export interface TopicPage { items: Topic[]; total: number; limit: number; offset: number }
export interface Summary { version: number; source_message_ids: string[]; [key: string]: unknown }
export interface LoginSession { user: { id: string; username: string; displayName: string }; csrfToken: string; expiresAt: string }
export interface Channel { id: string; name: string; type: number }
export interface Review { message_id: string; content: string; revision: number; topic_id: string | null; kind: string | null; job: { status: string; model_call_count: number; attempt_count: number; error_type: string | null } | null; latest_decision: unknown; latest_correction: unknown }
export interface SyncAction { action_id: string; type: string; status: string; attempt_count: number; error_type: string | null; superseded: boolean; discord_message_id: string | null; discord_thread_id: string | null }
export interface SyncState { topic_id: string; version: number; sync_paused: boolean; discord_thread_id: string | null; actions: SyncAction[]; limit: number; offset: number }
export interface ReviewedSummary { topic_id: string; expected_version: number; overview: string; proposals: string[]; decisions: string[]; open_questions: string[]; action_items: string[]; source_message_ids: string[] }
export interface SiteConfig { inviteUrl: string | null; supportUrl: string | null }
export interface PublicStatus {
  status: 'ok' | 'degraded' | 'unavailable' | 'unconfigured';
  database: 'ok' | 'unavailable' | 'unknown';
  worker: 'ok' | 'unavailable' | 'unknown';
  checkedAt: string;
}
