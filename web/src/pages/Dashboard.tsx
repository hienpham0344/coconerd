import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, ChevronDown, Hash, LayoutDashboard, Leaf, LogOut, Menu, MessageCircle, RefreshCw, Search, Settings2, Sprout, X, Sparkles } from 'lucide-react';
import { Brand, Flower } from '../components/Brand';
import { ErrorState, Loading, errorMessage, timeAgo } from '../components/Feedback';
import { GuildSettings } from '../components/GuildSettings';
import { ReviewPanel } from '../components/ReviewPanel';
import { resetDemo, demoGuildForTopic, type DashboardClient } from '../data/api';
import { clientForMode } from '../data/live';
import type { Guild, LoginSession, Mode, Overview, TopicPage, TopicStatus } from '../types';
import TopicDetail from './TopicDetail';

const statusLabel: Record<TopicStatus, string> = { ACTIVE: 'Đang nở', RESUMED: 'Tiếp nối', DORMANT: 'Tạm nghỉ', CLOSED: 'Đã khép lại' };
export function Status({ status }: { status: TopicStatus }) { return <span className={'status status-' + status.toLowerCase()}><i />{statusLabel[status] || status}</span>; }
export const guildName = (guild: Guild) => guild.name || 'Server ' + guild.guild_id;

export default function Dashboard({ route, mode = 'demo', api: providedApi, session, onLogout }: { route: string; mode?: Mode; api?: DashboardClient; session?: LoginSession; onLogout?: () => void }) {
  const api = useMemo(() => clientForMode(mode, session?.csrfToken, providedApi), [mode, session?.csrfToken, providedApi]);
  const requestedGuild = mode === 'live' ? route.match(/^\/app\/guilds\/(\d{15,22})(?:\/|$)/)?.[1] : undefined;
  const topicId = mode === 'live' ? route.match(/^\/app\/guilds\/\d+\/topics\/([\w-]+)$/)?.[1] : route.match(/^\/demo\/topics\/([\w-]+)$/)?.[1];
  const view = route.endsWith('/settings') ? 'settings' : route.endsWith('/review') ? 'review' : route.includes('/topics') ? 'topics' : 'overview';
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [guildId, setGuildId] = useState(() => mode === 'live' ? requestedGuild || '' : demoGuildForTopic(topicId) || '');
  const [initial, setInitial] = useState(true); const [error, setError] = useState('');
  const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TopicPage | null>(null); const [overview, setOverview] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false); const [loadError, setLoadError] = useState(''); const [revision, setRevision] = useState(0);
  const [menu, setMenu] = useState(false); const [messageInput, setMessageInput] = useState(''); const [reviewId, setReviewId] = useState('');
  const guild = requestedGuild ? guilds.find(g => g.guild_id === requestedGuild) : guilds.find(g => g.guild_id === guildId) || guilds[0];
  const base = mode === 'live' ? '/app/guilds/' + (guild?.guild_id || '') : '/demo';
  const reloadGuilds = useCallback(async () => {
    setError('');
    try { const result = await api.guilds(); setGuilds(result); setGuildId(current => result.some(g => g.guild_id === current) ? current : result[0]?.guild_id || ''); }
    catch (e) { setGuilds([]); setPage(null); setOverview(null); setError(errorMessage(e)); }
    finally { setInitial(false); }
  }, [api]);
  const refresh = useCallback(() => { void reloadGuilds(); setRevision(n => n + 1); }, [reloadGuilds]);
  useEffect(() => { void reloadGuilds(); }, [reloadGuilds]);
  useEffect(() => { const timer = setTimeout(() => { setSearch(query); setOffset(0); }, 250); return () => clearTimeout(timer); }, [query]);
  useEffect(() => {
    if (!guild || !['overview', 'topics'].includes(view)) return;
    let active = true; setBusy(true); setLoadError('');
    void Promise.all([api.topics(guild.guild_id, search, status, offset), api.overview(guild)])
      .then(([topics, counts]) => { if (active) { setPage(topics); setOverview(counts); } })
      .catch(e => { if (active) { setPage(null); setOverview(null); setLoadError(errorMessage(e)); } })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, guild, search, status, offset, revision, view]);
  useEffect(() => {
    if (mode !== 'live') return;
    const timer = setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 30000);
    return () => clearInterval(timer);
  }, [mode, refresh]);
  useEffect(() => { document.title = (view === 'settings' ? 'Cấu hình' : view === 'review' ? 'Review' : view === 'topics' ? 'Chủ đề' : 'Không gian') + ' — Coconerd'; setMenu(false); }, [view]);
  useEffect(() => { setReviewId(''); setMessageInput(''); setPage(null); setOverview(null); setOffset(0); }, [guild?.guild_id]);
  const selectGuild = (id: string) => {
    setGuildId(id); setOffset(0); setQuery(''); setStatus(''); setReviewId('');
    location.hash = mode === 'live' ? '/app/guilds/' + id : '/demo';
  };
  const heading = view === 'settings' ? 'Cấu hình Coconerd.' : view === 'review' ? 'Kiểm tra một tin nhắn.' : view === 'topics' ? 'Những câu chuyện của bạn.' : 'Để những kết nối lớn lên.';
  return <div className="workspace"><a className="skip-link" href="#workspace-main" onClick={e => { e.preventDefault(); document.getElementById('workspace-main')?.focus(); }}>Đến nội dung</a>
    {menu && <div className="sidebar-scrim" onClick={() => setMenu(false)} />}
    <aside className={'sidebar ' + (menu ? 'sidebar-open' : '')}>
      <div className="sidebar-brand"><Brand /><button className="icon-button sidebar-close" aria-label="Đóng menu" onClick={() => setMenu(false)}><X size={19} /></button></div>
      <div className="workspace-label">YOUR LITTLE GARDEN</div>
      <nav aria-label={mode === 'live' ? 'Quản trị server' : 'Khám phá minh họa'}>
        <a className={view === 'overview' ? 'active' : ''} href={'#' + base}><LayoutDashboard size={18} />Tổng quan<ArrowUpRight size={15} /></a>
        <a className={view === 'topics' ? 'active' : ''} href={'#' + base + '/topics'}><MessageCircle size={18} />Chủ đề{overview && <span className="nav-count">{overview.topics}</span>}</a>
        {mode === 'live' && <><a className={view === 'review' ? 'active' : ''} href={'#' + base + '/review'}><Search size={18} />Review tin nhắn</a><a className={view === 'settings' ? 'active' : ''} href={'#' + base + '/settings'}><Settings2 size={18} />Cấu hình server</a></>}
        <div className="nav-divider" /><a href="#/guide"><BookOpen size={18} />Hướng dẫn<ArrowUpRight size={14} /></a><a href="#/"><ArrowDownLeft size={18} />Về khu vườn</a>
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-garden"><Flower size={50} /><p>Good things<br /><em>grow together.</em></p></div>
        <div className="sidebar-user"><span className="avatar avatar-0"><Sprout size={19} /></span><div><strong>{session?.user.displayName || 'Bạn của khu vườn'}</strong><span>{mode === 'live' ? 'Quản trị viên Discord' : 'Đang ghé thăm'}</span></div></div>
        {onLogout && <button className="sidebar-logout" onClick={onLogout}><LogOut size={16} />Đăng xuất</button>}
      </div>
    </aside>
    <div className="workspace-content"><header className="workspace-header"><div><button className="icon-button dashboard-menu" aria-label="Mở menu" onClick={() => setMenu(true)}><Menu size={20} /></button><span className="breadcrumb">KHÔNG GIAN <span>/</span> {view === 'settings' ? 'CẤU HÌNH' : view === 'review' ? 'REVIEW' : view === 'overview' ? 'TỔNG QUAN' : 'CHỦ ĐỀ'}</span></div>
      <div className="workspace-header-right"><span className={'connection ' + (mode === 'demo' ? 'connection-demo' : '')}><i />{mode === 'live' ? 'Dữ liệu thật' : 'Bản trải nghiệm'}</span>
        {guilds.length > 0 && <div className="guild-picker"><span className="guild-avatar">{guild ? guildName(guild)[0] : 'C'}</span><select aria-label="Chọn server" value={guild?.guild_id || ''} onChange={e => selectGuild(e.target.value)}>{guilds.map(g => <option key={g.guild_id} value={g.guild_id}>{guildName(g)}</option>)}</select><ChevronDown size={14} /></div>}
      </div>
    </header>
    {mode === 'demo' && <div className="demo-banner"><Sparkles size={14} /><span>Bạn đang khám phá dữ liệu minh họa. Mọi thay đổi chỉ ở bản trải nghiệm.</span><button className="reset-demo" onClick={() => { resetDemo(); window.location.reload(); }}>Đặt lại mẫu</button><a href="#/app">Mở dashboard <ArrowUpRight size={14} /></a></div>}
    <main className="dashboard-main" id="workspace-main" tabIndex={-1}>
      {initial ? <Loading /> : error ? <ErrorState error={error} retry={refresh} /> : !guild ? <div className="empty-state"><h1>{mode === 'live' ? 'Chưa có server được phép quản trị.' : 'Chưa có không gian mẫu.'}</h1><p>{mode === 'live' ? 'Server cần được cấu hình với Coconerd và bạn phải là chủ server hoặc có quyền Administrator.' : 'Thử tải lại dữ liệu mẫu.'}</p><button className="button secondary small" onClick={() => { if (requestedGuild) location.hash = '/app'; refresh(); }}>Tải lại danh sách</button></div> : <>
        <div className="page-heading"><div><span className="eyebrow muted">{guildName(guild)}</span><h1>{heading}</h1><p>{view === 'settings' ? 'Chọn kênh, thời hạn lưu và cấu hình AI cho server.' : view === 'review' ? 'Đọc quyết định của bot và sửa phân loại khi cần.' : 'Tìm lại ý tưởng, theo dõi chủ đề và bắt kịp những điều đã bỏ lỡ.'}</p></div><button className="button secondary small" onClick={refresh} disabled={busy}><RefreshCw size={15} />Làm mới</button></div>
        {view === 'settings' && session ? <GuildSettings key={guild.guild_id} guildId={guild.guild_id} csrf={session.csrfToken} onChanged={refresh} /> : view === 'review' && session ? <section className="admin-panel">
          <form className="review-lookup" onSubmit={e => { e.preventDefault(); setReviewId(messageInput.trim()); }}><label htmlFor="review-message-id">ID tin nhắn Discord</label><div><input id="review-message-id" required pattern="\d{15,22}" value={messageInput} onChange={e => setMessageInput(e.target.value)} placeholder="Dán ID tin nhắn cần kiểm tra" /><button className="button secondary small">Xem tin nhắn</button></div></form>
          {reviewId && <ReviewPanel key={guild.guild_id + reviewId} guildId={guild.guild_id} messageId={reviewId} csrf={session.csrfToken} onChanged={() => { setReviewId(''); refresh(); }} />}
        </section> : <>
          {view === 'overview' && <><div className="welcome-garden"><div className="welcome-copy"><div className="welcome-tag"><Sprout size={13} /> YOUR CONVERSATIONS, IN BLOOM</div><h2>Ít điều lạc giữa dòng tin.<br />Nhiều điều để tìm thấy.</h2><p>{guild.enabled ? guild.allowed_channel_ids.length + ' kênh được chọn để những câu chuyện tìm về nhau.' : 'Server đang tạm dừng nhận tin mới.'}</p><a href={mode === 'live' ? '#' + base + '/settings' : '#/guide'} className="text-link">{mode === 'live' ? 'Cấu hình server' : 'Hướng dẫn sử dụng'}<ArrowUpRight size={16} /></a></div><div className="welcome-mascot"><img src="/assets/coconerd-bot.png" alt="Bot Coconerd chào bạn" width={1254} height={1254} decoding="async" /></div></div>
            <div className="stats-grid">{[{ icon: MessageCircle, label: 'Chủ đề được kết nối', value: overview?.topics }, { icon: Sprout, label: 'Chủ đề đang hoạt động', value: overview?.active_topics }, { icon: Leaf, label: 'Tin nhắn được lưu', value: overview?.messages }, { icon: Hash, label: 'Kênh được cho phép', value: overview?.channels }].map(({ icon: Icon, label, value }) => <div className="stat" key={label}><div><Icon size={17} /><span>{label}</span></div><strong>{value === undefined ? '—' : value.toLocaleString('vi')}</strong></div>)}</div>
          </>}
          <section className="topics-section"><div className="topics-heading"><div><h2>{view === 'overview' ? 'Những câu chuyện gần đây' : 'Tất cả chủ đề'}</h2><span>{page?.total ?? '—'} chủ đề {mode === 'demo' ? 'minh họa' : ''}</span></div>{view === 'overview' && <a className="text-link" href={'#' + base + '/topics'}>Xem tất cả<ArrowRight size={16} /></a>}</div>
            <div className="topic-toolbar"><label className="search-field"><Search size={17} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm một cuộc trò chuyện…" aria-label="Tìm chủ đề" />{query && <button className="icon-button" onClick={() => setQuery('')} aria-label="Xóa tìm kiếm"><X size={15} /></button>}</label><select className="filter-select" aria-label="Lọc trạng thái" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">Tất cả trạng thái</option><option value="ACTIVE">Đang nở</option><option value="RESUMED">Tiếp nối</option><option value="DORMANT">Tạm nghỉ</option><option value="CLOSED">Đã khép lại</option></select></div>
            {loadError ? <ErrorState error={loadError} retry={refresh} /> : busy ? <Loading label="Đang tìm những câu chuyện…" /> : !page?.items.length ? <div className="empty-state"><Search size={28} /><h3>{search || status ? 'Chưa tìm thấy câu chuyện phù hợp.' : 'Chưa có chủ đề.'}</h3><p>{search || status ? 'Thử một từ khóa hoặc trạng thái khác.' : 'Chủ đề xuất hiện khi bot xử lý tin nhắn từ các kênh được phép.'}</p></div> : <div className="topic-list">{page.items.map((topic, index) => <a className="topic-row" key={topic.topic_id} href={'#' + base + '/topics/' + encodeURIComponent(topic.topic_id)}><span className={'topic-flower topic-color-' + index % 4}><Flower size={27} /></span><div className="topic-row-copy"><h3>{topic.title}</h3><p>{topic.description || 'Một cuộc trò chuyện đang lớn lên.'}</p><div className="topic-mobile-meta"><Status status={topic.status} /><span>{timeAgo(topic.last_activity)}</span></div></div><Status status={topic.status} /><div className="topic-meta"><span><MessageCircle size={13} />{topic.message_count ?? '—'}</span><small>{timeAgo(topic.last_activity)}</small></div><ArrowUpRight className="topic-arrow" size={17} /></a>)}</div>}
            {page && page.total > 12 && <div className="pagination"><span>{offset + 1}–{Math.min(offset + 12, page.total)} / {page.total}</span><button className="icon-button" aria-label="Trang trước" disabled={!offset || busy} onClick={() => setOffset(o => Math.max(0, o - 12))}><ArrowLeft size={17} /></button><button className="icon-button" aria-label="Trang sau" disabled={offset + 12 >= page.total || busy} onClick={() => setOffset(o => o + 12)}><ArrowRight size={17} /></button></div>}
          </section>
        </>}
        <div className="dashboard-footnote"><Flower size={16} /><span>{mode === 'live' ? 'Dữ liệu thuộc server bạn đang quản trị.' : 'Một không gian minh họa để bạn thử và khám phá.'}</span></div>
      </>}
    </main></div>
    {topicId && guild && <TopicDetail key={guild.guild_id + topicId} guildId={guild.guild_id} topicId={topicId} mode={mode} api={api} csrf={session?.csrfToken} onClose={() => { location.hash = base + '/topics'; }} onChanged={refresh} />}
  </div>;
}
