import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Check, ChevronUp, Clock3, LockKeyhole, MessageCircle, Search, Sparkles, RefreshCw } from 'lucide-react';
import { Dialog } from '../components/Dialog';
import { Flower } from '../components/Brand';
import { ErrorState, Loading, errorMessage } from '../components/Feedback';
import { ReviewPanel } from '../components/ReviewPanel';
import { SyncPanel } from '../components/SyncPanel';
import type { DashboardClient } from '../data/api';
import { clientForMode } from '../data/live';
import { Status } from './Dashboard';
import type { Message, Mode, Summary, Topic } from '../types';

const summaryLabels: Record<string, string> = { overview: 'Câu chuyện đến lúc này', summary: 'Câu chuyện đến lúc này', key_points: 'Những điều đáng nhớ', proposals: 'Những ý tưởng được đề xuất', decisions: 'Những điều đã thống nhất', action_items: 'Việc cần làm tiếp theo', open_questions: 'Câu hỏi còn mở', keywords: 'Từ khóa', participants: 'Người tham gia', entities: 'Thông tin liên quan', title: 'Chủ đề', description: 'Nội dung' };
function SummaryValue({ value }: { value: unknown }) {
  if (typeof value === 'string' || typeof value === 'number') return <p>{String(value)}</p>;
  if (Array.isArray(value)) return <ul>{value.map((item, i) => <li key={i}><SummaryValue value={item} /></li>)}</ul>;
  if (value && typeof value === 'object') return <div>{Object.entries(value).map(([key, item]) => <div key={key}><strong>{summaryLabels[key] || key}</strong><SummaryValue value={item} /></div>)}</div>;
  return null;
}
function attachmentUrl(value?: string) {
  try { const url = new URL(value || ''); return url.protocol === 'https:' && ['cdn.discordapp.com', 'media.discordapp.net'].includes(url.hostname) && !url.username && !url.password ? url.href : undefined; }
  catch { return undefined; }
}

export default function TopicDetail({ guildId, topicId, mode, api: providedApi, csrf, onClose, onChanged }: { guildId: string; topicId: string; mode: Mode; api?: DashboardClient; csrf?: string; onClose: () => void; onChanged: () => void }) {
  const api = useMemo(() => clientForMode(mode, csrf, providedApi), [mode, csrf, providedApi]);
  const [topic, setTopic] = useState<Topic | null>(null); const [messages, setMessages] = useState<Message[]>([]); const [summary, setSummary] = useState<Summary | null>(null);
  const [tab, setTab] = useState('summary'); const [reviewId, setReviewId] = useState('');
  const [error, setError] = useState(''); const [operationError, setOperationError] = useState(''); const [busy, setBusy] = useState(true);
  const [more, setMore] = useState(false); const [loadingMore, setLoadingMore] = useState(false); const [confirm, setConfirm] = useState(false); const [closing, setClosing] = useState(false); const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true; setBusy(true); setError('');
    void (async () => {
      try {
        const data = await api.topic(guildId, topicId);
        const [items, result] = await Promise.all([api.messages(data), api.summary(data)]);
        if (active) { setTopic(data); setMessages(items); setSummary(result); setMore(items.length === 50); }
      } catch (e) { if (active) { setTopic(null); setMessages([]); setSummary(null); setError(errorMessage(e)); } }
      finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, [api, guildId, topicId, revision]);
  useEffect(() => {
    if (mode !== 'live' || !['summary', 'messages'].includes(tab)) return;
    const timer = setInterval(() => { if (document.visibilityState === 'visible') setRevision(n => n + 1); }, 30000);
    return () => clearInterval(timer);
  }, [mode, tab]);
  const loadMore = async () => {
    if (!topic) return; setLoadingMore(true); setOperationError('');
    try { const items = await api.messages(topic, messages.at(-1)?.created_at); setMessages(current => [...current, ...items.filter(m => !current.some(old => old.message_id === m.message_id))]); setMore(items.length === 50); }
    catch (e) { setOperationError(errorMessage(e)); } finally { setLoadingMore(false); }
  };
  const closeTopic = async () => {
    if (!topic) return; setClosing(true); setOperationError('');
    try { await api.close(topic); setTopic({ ...topic, status: 'CLOSED' }); setConfirm(false); onChanged(); }
    catch (e) { setOperationError(errorMessage(e)); } finally { setClosing(false); }
  };
  const corrected = () => { setTab('sync'); setReviewId(''); setRevision(n => n + 1); onChanged(); };
  return <Dialog title="MỘT CÂU CHUYỆN TRONG KHU VƯỜN" onClose={onClose} wide>
    {busy ? <Loading /> : error ? <ErrorState error={error} retry={() => setRevision(n => n + 1)} /> : topic && <>
      <div className="detail-heading"><span className="flower-icon"><Flower size={32} /></span><Status status={topic.status} /><h2>{topic.title}</h2><p>{topic.description}</p>
        <div className="detail-meta"><MessageCircle size={14} /><span>{messages.length}{more ? '+' : ''} tin đã tải</span><span>·</span><Clock3 size={14} /><span>{new Date(topic.last_activity).toLocaleDateString('vi-VN')}</span>
          {topic.discord_thread_id && /^\d+$/.test(topic.guild_id) && /^\d+$/.test(topic.discord_thread_id) && <a href={'https://discord.com/channels/' + topic.guild_id + '/' + topic.discord_thread_id} target="_blank" rel="noreferrer">Mở Discord <ArrowUpRight size={13} /></a>}
        </div>
      </div>
      <div className="detail-tabs" role="tablist" aria-label="Chi tiết chủ đề">
        <button role="tab" aria-selected={tab === 'summary'} onClick={() => setTab('summary')}><Sparkles size={16} />Tóm tắt</button>
        <button role="tab" aria-selected={tab === 'messages'} onClick={() => setTab('messages')}><MessageCircle size={16} />Hội thoại</button>
        {mode === 'live' && <button role="tab" aria-selected={tab === 'sync'} onClick={() => setTab('sync')}><RefreshCw size={16} />Đồng bộ</button>}
        {reviewId && <button role="tab" aria-selected={tab === 'review'} onClick={() => setTab('review')}><Search size={16} />Review</button>}
      </div>
      <div className="detail-content" role="tabpanel">
        {tab === 'sync' && csrf ? <SyncPanel guildId={guildId} topicId={topicId} csrf={csrf} onChanged={onChanged} /> : tab === 'review' && csrf && reviewId ? <ReviewPanel guildId={guildId} messageId={reviewId} csrf={csrf} onChanged={corrected} /> : tab === 'summary' ? summary ? <div className="summary-content">
          <div className="summary-caption"><Sparkles size={14} />{mode === 'demo' ? 'TÓM TẮT MINH HỌA' : 'TÓM TẮT BỞI AI'}<span>Phiên bản {summary.version}</span></div>
          {Object.entries(summary).filter(([key, value]) => !['version', 'source_message_ids'].includes(key) && value && (!Array.isArray(value) || value.length)).map(([key, value]) => <section key={key}><h3>{summaryLabels[key] || key.replaceAll('_', ' ')}</h3><SummaryValue value={value} /></section>)}
          {!!summary.source_message_ids?.length && <details className="summary-sources"><summary>Tin nhắn nguồn ({summary.source_message_ids.length})</summary><ul>{summary.source_message_ids.map(id => <li key={id}><code>{id}</code>{mode === 'live' && <button className="text-button" onClick={() => { setReviewId(id); setTab('review'); }}>Review</button>}</li>)}</ul></details>}
          <p className="small-note">Tóm tắt giúp theo dõi nhanh; hãy đối chiếu với tin nhắn gốc khi cần.</p>
        </div> : <div className="empty-state"><Sparkles size={28} /><h3>Chưa có bản tóm tắt.</h3><p>Bạn có thể đọc hội thoại gốc trong lúc chờ bot xử lý.</p></div> : <div className="message-history">
          {more && <button className="button secondary small load-more" disabled={loadingMore} onClick={() => void loadMore()}><ChevronUp size={14} />{loadingMore ? 'Đang tải…' : 'Xem tin nhắn cũ hơn'}</button>}
          {!messages.length && <div className="empty-state"><MessageCircle size={28} /><h3>Chưa có tin nhắn để hiển thị.</h3></div>}
          {[...messages].reverse().map((message, index) => <article className="message" key={message.message_id}>
            <span className={'avatar avatar-' + index % 3}>{message.author_name.slice(0, 1)}</span><div><header><strong>{message.author_name}</strong><time>{new Date(message.created_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</time></header><p>{message.content}</p>
              {message.attachments?.filter(item => attachmentUrl(item.url)).map((item, i) => <a className="attachment-link" key={i} href={attachmentUrl(item.url)} target="_blank" rel="noreferrer">{item.filename || 'Tệp đính kèm'}<ArrowUpRight size={13} /></a>)}
              {mode === 'live' && <button className="text-button message-review" onClick={() => { setReviewId(message.message_id); setTab('review'); }}>Review phân loại</button>}
            </div>
          </article>)}
        </div>}
      </div>
      {operationError && <p className="form-error" role="alert">{operationError}</p>}
      <div className="detail-footer">{confirm ? <div className="close-confirm"><p>Khép lại chủ đề này? Những tin mới sẽ không được gán vào đây.</p><div><button className="button secondary small" disabled={closing} onClick={() => setConfirm(false)}>Giữ lại</button><button className="button primary small" disabled={closing} onClick={() => void closeTopic()}>{closing ? 'Đang đóng…' : 'Xác nhận khép lại'}<Check size={14} /></button></div></div> : <><span className="small-note">{mode === 'demo' ? 'Thay đổi chỉ áp dụng cho dữ liệu mẫu.' : 'Dữ liệu thuộc server đang chọn.'}</span>{topic.status !== 'CLOSED' && <button className="button secondary small" onClick={() => setConfirm(true)}><LockKeyhole size={14} />Khép lại chủ đề</button>}</>}</div>
    </>}
  </Dialog>;
}
