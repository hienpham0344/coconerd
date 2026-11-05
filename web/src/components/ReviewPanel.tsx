import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { dashboardRequest, liveClient } from '../data/live';
import { ApiError } from '../data/api';
import { memoryFields, operationId, snapshotFor, validateSnapshots, type OperationDraft } from '../data/review';
import { ErrorState, Loading, errorMessage } from './Feedback';
import type { Review, ReviewedSummary, SyncState, Topic, TopicPage } from '../types';

const labels = { proposals: 'Đề xuất', decisions: 'Điều đã chốt', open_questions: 'Câu hỏi còn mở', action_items: 'Việc cần làm' };
export function ReviewPanel({ guildId, messageId, csrf, onChanged }: { guildId: string; messageId: string; csrf: string; onChanged: () => void }) {
  const api = useMemo(() => liveClient(csrf), [csrf]);
  const [review, setReview] = useState<Review | null>(null);
  const [target, setTarget] = useState(''); const [search, setSearch] = useState('');
  const [options, setOptions] = useState<Topic[]>([]);
  const [snapshots, setSnapshots] = useState<ReviewedSummary[]>([]);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [reason, setReason] = useState(''); const [error, setError] = useState('');
  const [busy, setBusy] = useState(true); const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [saving, setSaving] = useState(false); const [revision, setRevision] = useState(0);
  const [conflict, setConflict] = useState(false);
  const operation = useRef<OperationDraft>({});
  useEffect(() => {
    let active = true; setBusy(true); setReview(null); setError(''); setConflict(false);
    void dashboardRequest<Review>(guildId, 'messages/' + encodeURIComponent(messageId) + '/review', csrf)
      .then(value => { if (active) { setReview(value); setTarget(value.topic_id || ''); } })
      .catch(e => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [guildId, messageId, csrf, revision]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      void dashboardRequest<TopicPage>(guildId, 'topics?limit=100&q=' + encodeURIComponent(search), csrf)
        .then(value => { if (active) setOptions(value.items); }).catch(e => { if (active) setError(errorMessage(e)); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [guildId, csrf, search]);
  useEffect(() => {
    if (!review) return;
    let active = true; setSnapshots([]); setLoadingSnapshots(true); setError('');
    const ids = [...new Set([review.topic_id, target || null].filter((id): id is string => !!id))];
    void Promise.all(ids.map(async id => {
      const topic = await api.topic(guildId, id);
      const [summary, sync] = await Promise.all([api.summary(topic), dashboardRequest<SyncState>(guildId, 'topics/' + encodeURIComponent(id) + '/sync?limit=1', csrf)]);
      return { topic, snapshot: snapshotFor(id, summary, sync.version, messageId, target || null, review.topic_id) };
    })).then(items => {
      if (active) { setSnapshots(items.map(item => item.snapshot)); setTitles(Object.fromEntries(items.map(item => [item.topic.topic_id, item.topic.title]))); }
    }).catch(e => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setLoadingSnapshots(false); });
    return () => { active = false; };
  }, [api, guildId, review, target, csrf, messageId]);
  const update = (id: string, patch: Partial<ReviewedSummary>) => setSnapshots(items => items.map(item => item.topic_id === id ? { ...item, ...patch } : item));
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!review || loadingSnapshots) return;
    setSaving(true); setError('');
    try {
      validateSnapshots(snapshots);
      const body = { reason, expected_revision: review.revision, target_topic_id: target || null, summaries: snapshots };
      await dashboardRequest(guildId, 'messages/' + encodeURIComponent(messageId) + '/corrections', csrf, 'POST', { ...body, request_id: operationId(operation.current, body) });
      onChanged();
    } catch (e) { setError(errorMessage(e)); setConflict(e instanceof ApiError && e.status === 409); } finally { setSaving(false); }
  }
  if (busy) return <Loading label="Đang đọc quyết định phân loại…" />;
  if (!review) return <ErrorState error={error} retry={() => setRevision(n => n + 1)} />;
  return <form className="admin-form review-panel" onSubmit={event => void submit(event)}>
    <h3>Review tin nhắn</h3><blockquote>{review.content}</blockquote>
    <p className="small-note">Revision {review.revision} · {review.kind || 'Chưa phân loại'}{review.job && ' · ' + review.job.status + ' · ' + review.job.model_call_count + ' lượt AI'}</p>
    {review.job?.error_type && <p className="form-error">{review.job.error_type}</p>}
    <details><summary>Quyết định AI và lần sửa gần nhất</summary><pre className="admin-json">{JSON.stringify({ decision: review.latest_decision, correction: review.latest_correction }, null, 2)}</pre></details>
    <fieldset disabled={saving}>
      <label>Tìm chủ đề đích<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Tìm trong server này…" /></label>
      <label>Gán tin nhắn vào<select value={target} onChange={e => setTarget(e.target.value)}>
        <option value="">Để chưa gán chủ đề</option>
        {target && !options.some(topic => topic.topic_id === target) && <option value={target}>{titles[target] || target}</option>}
        {options.filter(topic => topic.status !== 'CLOSED' || topic.topic_id === review.topic_id).map(topic => <option key={topic.topic_id} value={topic.topic_id}>{topic.title}{topic.status === 'CLOSED' ? ' (đã đóng)' : ''}</option>)}
      </select></label>
      <p className="small-note">Kiểm tra lại toàn bộ nội dung ghi nhớ của từng chủ đề sau khi chuyển tin. Các mục dưới đây sẽ thay thế memory hiện tại.</p>
      {loadingSnapshots ? <Loading label="Đang tải memory và phiên bản chủ đề…" /> : snapshots.map(item => <section className="memory-editor" key={item.topic_id}>
        <h4>{titles[item.topic_id] || item.topic_id} <small>· phiên bản {item.expected_version}</small></h4>
        <label>Tóm tắt<textarea rows={4} maxLength={10000} value={item.overview} onChange={e => update(item.topic_id, { overview: e.target.value })} /></label>
        {memoryFields.map(field => <label key={field}>{labels[field]} <span className="small-note">(mỗi dòng một mục)</span><textarea rows={3} value={item[field].join('\n')} onChange={e => update(item.topic_id, { [field]: e.target.value.split('\n') })} onBlur={e => update(item.topic_id, { [field]: e.target.value.split('\n').map(text => text.trim()).filter(Boolean) })} /></label>)}
        <label>ID tin nhắn nguồn <span className="small-note">(mỗi dòng một ID)</span><textarea rows={3} value={item.source_message_ids.join('\n')} onChange={e => update(item.topic_id, { source_message_ids: e.target.value.split('\n') })} onBlur={e => update(item.topic_id, { source_message_ids: e.target.value.split(/[\s,]+/).filter(Boolean) })} /></label>
      </section>)}
      <label>Lý do sửa<textarea required maxLength={1000} rows={2} value={reason} onChange={e => setReason(e.target.value)} /></label>
      {error && <ErrorState error={error} retry={() => setRevision(n => n + 1)} />}
      <p className="small-note">Sau khi sửa, các chủ đề liên quan tạm dừng đồng bộ để bạn đối chiếu dữ liệu trên Discord.</p>
      <button className="button primary small" disabled={loadingSnapshots || conflict || snapshots.length !== new Set([review.topic_id, target || null].filter(Boolean)).size}>{saving ? 'Đang lưu…' : 'Lưu bản sửa và tạm dừng đồng bộ'}</button>
    </fieldset>
  </form>;
}
