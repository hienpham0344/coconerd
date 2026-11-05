import type { ReviewedSummary } from '../types';

export const memoryFields = ['proposals', 'decisions', 'open_questions', 'action_items'] as const;
export function snapshotFor(topicId: string, summary: Record<string, unknown> | null, version: number, messageId: string, target: string | null, previous: string | null): ReviewedSummary {
  const sources = Array.isArray(summary?.source_message_ids) ? summary.source_message_ids.filter((id): id is string => typeof id === 'string') : [];
  const result: ReviewedSummary = {
    topic_id: topicId, expected_version: version,
    overview: typeof summary?.overview === 'string' ? summary.overview : typeof summary?.summary === 'string' ? summary.summary : '',
    proposals: [], decisions: [], open_questions: [], action_items: [],
    source_message_ids: sources.filter(id => !(topicId === previous && target !== previous && id === messageId)),
  };
  for (const field of memoryFields) {
    if (Array.isArray(summary?.[field])) result[field] = (summary[field] as unknown[]).filter((item): item is string => typeof item === 'string');
  }
  if (topicId === target && target !== previous && !result.source_message_ids.includes(messageId)) result.source_message_ids.push(messageId);
  return result;
}

export function validateSnapshots(snapshots: ReviewedSummary[]) {
  for (const item of snapshots) {
    if (new Set(item.source_message_ids).size !== item.source_message_ids.length) throw new Error('ID nguồn không được trùng nhau.');
    if (!item.source_message_ids.length && (item.overview.trim() || memoryFields.some(field => item[field].length))) throw new Error('Memory có nội dung cần ít nhất một tin nhắn nguồn. Hãy sửa memory và nguồn trước khi lưu.');
    if (item.overview.length > 10000 || memoryFields.some(field => item[field].length > 50 || item[field].some(text => !text.trim() || text.length > 2000)) || item.source_message_ids.length > 500) throw new Error('Memory hoặc nguồn vượt giới hạn cho phép.');
  }
}

export interface OperationDraft { fingerprint?: string; id?: string }
export function operationId(draft: OperationDraft, body: unknown): string {
  const fingerprint = JSON.stringify(body);
  if (fingerprint !== draft.fingerprint || !draft.id) {
    draft.fingerprint = fingerprint; draft.id = crypto.randomUUID();
  }
  return draft.id;
}
