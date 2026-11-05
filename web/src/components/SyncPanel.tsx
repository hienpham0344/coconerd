import { useEffect, useRef, useState, type FormEvent } from 'react';
import { dashboardRequest } from '../data/live';
import { ApiError } from '../data/api';
import { operationId, type OperationDraft } from '../data/review';
import { ErrorState, Loading, errorMessage } from './Feedback';
import type { SyncAction, SyncState } from '../types';

export function SyncPanel({ guildId, topicId, csrf, onChanged }: { guildId: string; topicId: string; csrf: string; onChanged: () => void }) {
  const [state, setState] = useState<SyncState | null>(null); const [offset, setOffset] = useState(0);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(true); const [saving, setSaving] = useState(false); const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<SyncAction | null>(null);
  const [reason, setReason] = useState(''); const [confirmed, setConfirmed] = useState(false);
  const [threadId, setThreadId] = useState(''); const [messageId, setMessageId] = useState('');
  const [resolution, setResolution] = useState('');
  const [conflict, setConflict] = useState(false);
  const operation = useRef<OperationDraft>({});
  useEffect(() => {
    let active = true; setBusy(true); setError(''); setSelected(null); setConfirmed(false); setReason(''); setConflict(false);
    void dashboardRequest<SyncState>(guildId, 'topics/' + encodeURIComponent(topicId) + '/sync?limit=50&offset=' + offset, csrf)
      .then(value => { if (active) { setState(value); setThreadId(value.discord_thread_id || ''); } })
      .catch(e => { if (active) { setState(null); setError(errorMessage(e)); } }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [guildId, topicId, csrf, offset, revision]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!state || !confirmed) return;
    setSaving(true); setError(''); setNotice('');
    const body = selected ? {
      reason, expected_attempt_count: selected.attempt_count, resolution,
      ...(threadId ? { discord_thread_id: threadId } : {}), ...(messageId ? { discord_message_id: messageId } : {}),
    } : { reason, expected_version: state.version, discord_reconciled: true, discord_thread_id: threadId };
    try {
      await dashboardRequest(guildId, selected ? 'actions/' + encodeURIComponent(selected.action_id) + '/recover' : 'topics/' + encodeURIComponent(topicId) + '/resume-sync', csrf, 'POST', { ...body, request_id: operationId(operation.current, body) });
      setNotice(selected ? 'Đã ghi nhận kết quả khôi phục.' : 'Đã mở lại đồng bộ cho các thay đổi mới.');
      setRevision(n => n + 1); onChanged();
    } catch (e) { setError(errorMessage(e)); setConflict(e instanceof ApiError && e.status === 409); } finally { setSaving(false); }
  }
  if (busy) return <Loading label="Đang tải trạng thái đồng bộ…" />;
  if (!state) return <ErrorState error={error} retry={() => setRevision(n => n + 1)} />;
  return <div className="sync-panel">
    <div className="admin-section-heading"><div><h3>{state.sync_paused ? 'Đồng bộ đang tạm dừng' : 'Đồng bộ đang hoạt động'}</h3><p className="small-note">Phiên bản chủ đề {state.version}</p></div><button className="button secondary small" onClick={() => setRevision(n => n + 1)}>Tải lại</button></div>
    {notice && <p role="status" className="save-notice">{notice}</p>}
    <div className="action-history">{state.actions.map(action => <article key={action.action_id}>
      <div><strong>{action.type}</strong><span>{action.status}{action.superseded ? ' · đã thay thế' : ''} · {action.attempt_count} lượt</span>{action.error_type && <small>{action.error_type}</small>}</div>
      {!action.superseded && ['DEAD', 'CLAIMED'].includes(action.status) && <button className="button secondary small" disabled={saving} onClick={() => { setSelected(action); setConfirmed(false); setReason(''); setResolution(''); setMessageId(action.discord_message_id || ''); setThreadId(action.discord_thread_id || state.discord_thread_id || ''); setError(''); }}>Khôi phục</button>}
    </article>)}
      {!state.actions.length && <p className="small-note">Chưa có action ở trang này.</p>}
    </div>
    <div className="pagination"><button className="button secondary small" disabled={offset === 0 || saving} onClick={() => setOffset(n => Math.max(0, n - 50))}>Trang trước</button><span>Từ action {offset + 1}</span><button className="button secondary small" disabled={state.actions.length < 50 || saving} onClick={() => setOffset(n => n + 50)}>Trang sau</button></div>
    {(state.sync_paused || selected) && <form className="admin-form memory-editor" onSubmit={event => void submit(event)}><fieldset disabled={saving}>
      <h3>{selected ? 'Đối chiếu action trên Discord' : 'Mở lại đồng bộ'}</h3>
      {selected && <><p className="small-note">Chỉ khôi phục action lỗi hoặc lease đã hết hạn. Xác minh trên Discord trước khi ghi nhận để tránh gửi trùng.</p><label>Kết quả đối chiếu<select required value={resolution} onChange={e => setResolution(e.target.value)}>
        <option value="">Chọn kết quả</option><option value="performed">Thao tác đã được thực hiện trên Discord</option><option value="not_performed">Chưa thực hiện; cấp thêm một lượt thử</option>
      </select></label></>}
      <label>ID thread Discord<input value={threadId} required={!selected || (resolution === 'performed' && selected.type === 'CREATE_THREAD')} pattern="\d{15,22}" onChange={e => setThreadId(e.target.value)} /></label>
      {selected && <label>ID tin nhắn Discord<input value={messageId} required={resolution === 'performed' && ['APPEND_MESSAGE', 'UPSERT_SUMMARY'].includes(selected.type)} pattern="\d{15,22}" onChange={e => setMessageId(e.target.value)} /></label>}
      <label>Lý do<textarea required maxLength={1000} value={reason} rows={2} onChange={e => setReason(e.target.value)} /></label>
      <label className="check-line"><input required type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Tôi đã đối chiếu tin nhắn, tóm tắt và thread trên Discord.</label>
      {error && <ErrorState error={error} retry={() => setRevision(n => n + 1)} />}
      <div className="form-actions">{selected && <button className="button secondary small" type="button" onClick={() => { setSelected(null); setReason(''); setConfirmed(false); setError(''); }}>Hủy khôi phục</button>}<button className="button primary small" disabled={!confirmed || conflict}>{saving ? 'Đang lưu…' : selected ? 'Xác nhận khôi phục' : 'Xác nhận mở lại đồng bộ'}</button></div>
    </fieldset></form>}
    {error && !state.sync_paused && !selected && <ErrorState error={error} retry={() => setRevision(n => n + 1)} />}
  </div>;
}
