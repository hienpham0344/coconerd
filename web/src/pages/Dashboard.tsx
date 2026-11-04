import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownLeft, ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, Hash, LayoutDashboard, Leaf, Menu, MessageCircle, RefreshCw, Search, Sprout, X, Sparkles } from 'lucide-react';
import { Brand, Flower } from '../components/Brand';
import { ErrorState, Loading, errorMessage, timeAgo } from '../components/Feedback';
import { client, resetDemo, demoGuildForTopic } from '../data/api';
import type { Guild, Mode, Overview, Topic, TopicPage, TopicStatus } from '../types';
import TopicDetail from './TopicDetail';

const statusLabel: Record<TopicStatus, string> = { ACTIVE: 'In Bloom', RESUMED: 'Resumed', DORMANT: 'Dormant', CLOSED: 'Closed' };
export function Status({ status }: { status: TopicStatus }) { return <span className={`status status-${status.toLowerCase()}`}><i />{statusLabel[status] || status}</span>; }
export const guildName = (guild: Guild) => guild.name || `Server ${guild.guild_id}`;

export default function Dashboard({ route }: { route: string }) {
  const mode: Mode = 'demo';
  const api = useMemo(() => client(), []);
  const view = route.startsWith('/demo/topics') ? 'topics' : 'overview';
  const topicId = route.match(/^\/demo\/topics\/([\w-]+)$/)?.[1];
  const [guilds, setGuilds] = useState<Guild[]>([]); const [guildId, setGuildId] = useState(() => demoGuildForTopic(topicId) || localStorage.getItem('coconerd-demo-selected-guild') || '');
  const [initial, setInitial] = useState(true); const [error, setError] = useState(''); const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TopicPage | null>(null); const [overview, setOverview] = useState<Overview | null>(null); const [busy, setBusy] = useState(false); const [loadError, setLoadError] = useState(''); const [revision, setRevision] = useState(0);
  const [menu, setMenu] = useState(false);
  const [guildOpen, setGuildOpen] = useState(false);
  const guildDropdownRef = useRef<HTMLDivElement>(null);
  const guild = guilds.find(g => g.guild_id === guildId) || guilds[0];
  const reloadGuilds = useCallback(async () => { setError(''); try { const result = await api.guilds(); setGuilds(result); setGuildId(current => result.some(g => g.guild_id === current) ? current : result[0]?.guild_id || ''); } catch (e) { setError(errorMessage(e)); } finally { setInitial(false); } }, [api]);
  useEffect(() => { void reloadGuilds(); }, [reloadGuilds]);

  useEffect(() => {
    if (!guildOpen) return;
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      if (guildDropdownRef.current && !guildDropdownRef.current.contains(e.target as Node)) {
        setGuildOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setGuildOpen(false);
    };
    window.addEventListener('mousedown', onPointerDown);
    window.addEventListener('touchstart', onPointerDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('touchstart', onPointerDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [guildOpen]);

  useEffect(() => { const timer = setTimeout(() => { setSearch(query); setOffset(0); }, 250); return () => clearTimeout(timer); }, [query]);
  useEffect(() => {
    if (!guild) return;
    let active = true; setBusy(true); setLoadError('');
    void Promise.all([api.topics(guild.guild_id, search, status, offset), api.overview(guild)]).then(([topics, counts]) => { if (active) { setPage(topics); setOverview(counts); } }).catch(e => { if (active) setLoadError(errorMessage(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, guild, search, status, offset, revision]);
  useEffect(() => { document.title = `${view === 'topics' ? 'Topics' : 'Workspace'} — Coconerd`; setMenu(false); }, [view]);
  const selectGuild = (id: string) => { setGuildId(id); localStorage.setItem('coconerd-demo-selected-guild', id); setOffset(0); setQuery(''); setStatus(''); setGuildOpen(false); if (topicId) location.hash = '/demo/topics'; };

  const refresh = () => { void reloadGuilds(); setRevision(n => n + 1); };

  return <div className="workspace"><a className="skip-link" href="#workspace-main" onClick={e => { e.preventDefault(); document.getElementById('workspace-main')?.focus(); }}>Skip to content</a>{menu && <div className="sidebar-scrim" onClick={() => setMenu(false)} />}
    <aside className={`sidebar ${menu ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><Brand /><button className="icon-button sidebar-close" aria-label="Close menu" onClick={() => setMenu(false)}><X size={19} /></button></div><div className="workspace-label">YOUR LITTLE GARDEN</div><nav aria-label="Demo navigation"><a className={view === 'overview' ? 'active' : ''} href="#/demo"><LayoutDashboard size={18} />Overview<ArrowUpRight size={15} /></a><a className={view === 'topics' ? 'active' : ''} href="#/demo/topics"><MessageCircle size={18} />Topics{overview && <span className="nav-count">{overview.topics}</span>}</a><div className="nav-divider" /><a href="#/guide"><BookOpen size={18} />Guide<ArrowUpRight size={14} /></a><a href="#/"><ArrowDownLeft size={18} />Back to landing</a></nav><div className="sidebar-bottom"><div className="sidebar-garden"><Flower size={50} /><p>Good things<br /><em>grow together.</em></p></div><div className="sidebar-user"><span className="avatar avatar-0"><Sprout size={19} /></span><div><strong>Garden Friend</strong><span>Visiting guest</span></div></div></div></aside>
    <div className="workspace-content"><header className="workspace-header"><div><button className="icon-button dashboard-menu" aria-label="Open menu" onClick={() => setMenu(true)}><Menu size={20} /></button><span className="breadcrumb">WORKSPACE <span>/</span> {view === 'overview' ? 'OVERVIEW' : 'TOPICS'}</span></div><div className="workspace-header-right"><span className="connection connection-demo"><i />Interactive Demo</span>{guilds.length > 0 && <div className="guild-picker-wrapper" ref={guildDropdownRef}><button type="button" className="guild-picker" aria-label="Select server" aria-haspopup="listbox" aria-expanded={guildOpen} onClick={() => setGuildOpen(open => !open)}><span className="guild-avatar">{guild ? guildName(guild)[0] : 'C'}</span><span className="guild-picker-name">{guild ? guildName(guild) : 'Select server'}</span><ChevronDown size={14} className={`guild-picker-chevron ${guildOpen ? 'open' : ''}`} /></button>{guildOpen && <div className="guild-dropdown-menu" role="listbox" aria-label="Select server">{guilds.map(g => { const isSelected = guild?.guild_id === g.guild_id; return <button key={g.guild_id} type="button" role="option" aria-selected={isSelected} className={`guild-dropdown-item ${isSelected ? 'active' : ''}`} onClick={() => selectGuild(g.guild_id)}><span className="guild-avatar">{guildName(g)[0]}</span><span className="guild-dropdown-item-name">{guildName(g)}</span>{isSelected && <Check size={14} className="guild-dropdown-check" />}</button>; })}</div>}<select aria-label="Select server" value={guild?.guild_id || ''} onChange={e => selectGuild(e.target.value)} tabIndex={-1} aria-hidden="true" className="guild-picker-select-hidden">{guilds.map(g => <option key={g.guild_id} value={g.guild_id}>{guildName(g)}</option>)}</select></div>}</div></header>
    {mode === 'demo' && <div className="demo-banner"><Sparkles size={14} /><span>You are exploring demo data. All changes remain in the interactive demo.</span><button className="reset-demo" onClick={() => { resetDemo(); window.location.reload(); }} aria-label="Reset demo data">Reset Demo</button><a href="#/invite">Add to Discord <ArrowUpRight size={14} /></a></div>}
    <main className="dashboard-main" id="workspace-main" tabIndex={-1}>{initial ? <Loading /> : error ? <ErrorState error={error} retry={() => void reloadGuilds()} /> : !guild ? <div className="empty-state"><h1>No demo workspace found.</h1><button onClick={refresh}>Retry</button></div> : <>
      <div className="page-heading"><div><span className="eyebrow muted">{view === 'overview' ? 'WELCOME TO THE GARDEN' : 'EVERY IDEA HAS A PLACE'}</span><h1>{view === 'overview' ? 'Where connections take root and bloom.' : 'Your community stories.'}</h1><p>{view === 'overview' ? 'A little order makes room for deeper, calmer conversations.' : 'Revisit ideas, follow topic threads, and catch up on what you missed.'}</p></div><button className="button secondary small" onClick={refresh} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />Refresh</button></div>
      {view === 'overview' && <><div className="welcome-garden"><div><span className="eyebrow">A CALMER CORNER OF DISCORD</span><h2>Less noise in the chat.<br />More ideas to discover.</h2><p>{guild.enabled ? `${guild.allowed_channel_ids.length} channels selected to organize discussions.` : 'Server ingestion is currently paused. You can re-enable it in settings.'}</p><a href="#/guide" className="text-link">User Guide <ArrowUpRight size={16} /></a></div><div className="welcome-mascot"><img src="/assets/coconerd-bot.png" alt="Coconerd Bot welcoming you" width={1254} height={1254} decoding="async" /></div></div><div className="stats-grid">{[{ icon: MessageCircle, label: 'Connected topics', value: overview?.topics }, { icon: Sprout, label: 'Active topics', value: overview?.active_topics }, { icon: Leaf, label: 'Messages organized', value: overview?.messages }, { icon: Hash, label: 'Monitored channels', value: overview?.channels }].map(({ icon: Icon, label, value }) => <div className="stat" key={label}><div><Icon size={17} /><span>{label}</span></div><strong>{value === undefined ? '—' : value.toLocaleString('en-US')}</strong></div>)}</div></>}
      <section className="topics-section"><div className="topics-heading"><div><h2>{view === 'overview' ? 'Recent Discussions' : 'All Topics'}</h2><span>{page?.total ?? '—'} {page?.total === 1 ? 'topic' : 'topics'} {mode === 'demo' ? 'in demo' : ''}</span></div>{view === 'overview' && <a className="text-link" href="#/demo/topics">View all <ArrowRight size={16} /></a>}</div><div className="topic-toolbar"><label className="search-field"><Search size={17} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search discussions…" aria-label="Search topics" />{query && <button className="icon-button" onClick={() => setQuery('')} aria-label="Clear search"><X size={15} /></button>}</label><select className="filter-select" aria-label="Filter status" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">All statuses</option><option value="ACTIVE">In Bloom</option><option value="RESUMED">Resumed</option><option value="DORMANT">Dormant</option><option value="CLOSED">Closed</option></select></div>{loadError ? <ErrorState error={loadError} retry={refresh} /> : busy ? <Loading label="Finding discussions…" /> : !page?.items.length ? <div className="empty-state"><Search size={28} /><h3>{search || status ? 'No matching discussions found.' : 'The first story awaits.'}</h3><p>{search || status ? 'Try a different keyword or status filter.' : 'When messages arrive from monitored channels, topics will appear here.'}</p>{(search || status) && <button className="text-button" onClick={() => { setQuery(''); setStatus(''); }}>Clear filters</button>}</div> : <div className="topic-list">{page.items.map((topic, index) => <a className="topic-row" key={topic.topic_id} href={`#/demo/topics/${encodeURIComponent(topic.topic_id)}`}><span className={`topic-flower topic-color-${index % 4}`}><Flower size={27} /></span><div className="topic-row-copy"><h3>{topic.title}</h3><p>{topic.description || 'A discussion in progress.'}</p><div className="topic-mobile-meta"><Status status={topic.status} /><span>{timeAgo(topic.last_activity)}</span></div></div><Status status={topic.status} /><div className="topic-meta"><span><MessageCircle size={13} />{topic.message_count ?? '—'}</span><small>{timeAgo(topic.last_activity)}</small></div><ArrowUpRight className="topic-arrow" size={17} /></a>)}</div>}{page && page.total > 12 && <div className="pagination"><span>{offset + 1}–{Math.min(offset + 12, page.total)} / {page.total}</span><button className="icon-button" aria-label="Previous page" disabled={!offset || busy} onClick={() => setOffset(o => Math.max(0, o - 12))}><ArrowLeft size={17} /></button><button className="icon-button" aria-label="Next page" disabled={offset + 12 >= page.total || busy} onClick={() => setOffset(o => o + 12)}><ArrowRight size={17} /></button></div>}</section>
      <div className="dashboard-footnote"><Flower size={16} /><span>An interactive demo space to explore and experiment.</span></div>
    </>}</main></div>
    {topicId && guild && <TopicDetail key={`${guild.guild_id}-${topicId}`} guildId={guild.guild_id} topicId={topicId} mode={mode} onClose={() => { location.hash = '/demo/topics'; }} onChanged={refresh} />}

  </div>;
}
