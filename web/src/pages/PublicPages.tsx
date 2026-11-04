import { useEffect, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown, Hash, Leaf, LockKeyhole, MessageCircle, RefreshCw, Search, ShieldCheck, Sparkles } from 'lucide-react';
import { Flower } from '../components/Brand';
import { PublicLayout, PageIntro } from '../components/PublicLayout';
import { errorMessage } from '../components/Feedback';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { request } from '../data/api';
import { faqs, matchesText } from '../data/content';
import type { PublicStatus, SiteConfig } from '../types';

function Features() {
  return <PublicLayout active="/features" title="Features">
    <PageIntro eyebrow="WHAT COCONERD CAN DO" title={<>Every conversation,<br /><em>its own thread.</em></>}>Keep related ideas together, catch up on what you missed, and let your community keep chatting naturally.</PageIntro>
    <div className="feature-stories">
      <section className="feature-story">
        <div className="feature-story-copy"><span className="eyebrow lime">01 / CONNECTING CONVERSATIONS</span><h2>Multiple discussions at once.<br />Still in sync.</h2><p>A single Discord channel often hosts multiple overlapping conversations. Coconerd uses context and reply links to connect messages that share a common thread.</p><p>When a conversation resumes, the bot picks up the existing thread. Original messages remain exactly where you sent them.</p><a href="#/demo/topics/a-little-garden" className="text-link">Explore a sample topic <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual topic-visual"><div className="visual-caption"><span><Hash size={14} />general</span><span>SIMULATED</span></div><div className="sample-chat"><p><span className="sample-person">L</span><span><strong>Linh</strong>Shall we work on the website this weekend?</span></p><p><span className="sample-person sample-person-olive">A</span><span><strong>An</strong>Anyone got a good playlist for focus?</span></p><p><span className="sample-person">M</span><span><strong>Minh</strong>I have a few ideas for the layout.</span></p></div><div className="topic-branches"><div><MessageCircle size={17} /><span>New Website<small>Linh · Minh</small></span><span className="branch-dot" /></div><div><Leaf size={17} /><span>Weekend Playlist<small>An</small></span><span className="branch-dot" /></div></div><span className="visual-footnote">One shared channel. Distinct conversational threads.</span></div>
      </section>
      <section className="feature-story feature-story-reverse">
        <div className="feature-story-copy"><span className="eyebrow lime">02 / CATCHING UP</span><h2>Step away from the keyboard.<br />Return right in sync.</h2><p>Structured summaries capture key points, agreed decisions, and open questions. Know where the discussion stands before diving deeper.</p><p>A summary is just the starting point. For critical information, always verify against the original messages.</p><a href="#/demo/topics/new-website" className="text-link">Read a sample summary <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual summary-visual"><div className="visual-caption"><span><Sparkles size={15} />Idea Corner: New Website</span><span>SIMULATED</span></div><span className="summary-kicker">THE STORY SO FAR</span><h3>A cozy corner,<br />close to nature.</h3><p>The team is exploring design directions for Coconerd's new website.</p><ul><li><Check size={14} />Cream accents and dark backgrounds, inspired by the garden.</li><li><Check size={14} />Gentle motion, keeping content effortless to read.</li></ul><div className="summary-open-question"><span>STILL DISCUSSING</span>What interactive details should we include?</div><span className="visual-footnote">Key points for a quick read. Original messages for verification.</span></div>
      </section>
      <section className="feature-story">
        <div className="feature-story-copy"><span className="eyebrow lime">03 / BOUNDARIES THAT MATTER</span><h2>Your community garden.<br />Boundaries you choose.</h2><p>Administrators choose which servers and channels the bot can listen to. You can pause ingestion whenever needed.</p><p>Retention periods are customized to your community; expired data is pruned according to your storage policies.</p><a href="#/privacy" className="text-link">See how data is handled <ArrowUpRight size={17} /></a></div>
        <div className="feature-visual channels-visual"><div className="visual-caption"><span><ShieldCheck size={15} />Operational Scope</span><span>SIMULATED</span></div><h3>Listens only<br />where authorized.</h3><div className="sample-channel"><Hash size={18} /><span>general</span><span><Check size={13} />Authorized</span></div><div className="sample-channel"><Hash size={18} /><span>ideas</span><span><Check size={13} />Authorized</span></div><div className="sample-channel channel-private"><LockKeyhole size={17} /><span>private-chat</span><span>Out of scope</span></div><span className="visual-footnote"><Leaf size={14} />Monitored scope and retention periods are decided by administrators.</span></div>
      </section>
    </div>
    <div className="public-next"><p>Dip into an interactive conversation.</p><a className="pill" href="#/demo">Open Interactive Demo <ArrowUpRight size={16} /></a></div>
  </PublicLayout>;
}

function HelpAvailability() {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [errors, setErrors] = useState({ links: '', status: '' });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setConfig(null); setStatus(null); setErrors({ links: '', status: '' });
    void request<SiteConfig>('/api/site').then(result => { if (active) setConfig(result); }).catch(cause => { if (active) setErrors(current => ({ ...current, links: errorMessage(cause) })); });
    void request<PublicStatus>('/api/status').then(result => { if (active) setStatus(result); }).catch(cause => { if (active) setErrors(current => ({ ...current, status: errorMessage(cause) })); });
    return () => { active = false; };
  }, [revision]);
  const labels = { ok: 'Service is operational', degraded: 'Partially degraded service', unavailable: 'Service unavailable', unconfigured: 'Bot status unconfigured' };
  const componentLabels = { ok: 'operational', unavailable: 'unavailable', unknown: 'unverified' };
  return <section className="help-contact" id="help-contact"><div className="help-contact-heading"><span className="eyebrow lime">03 / WHEN YOU NEED MORE</span><button className="icon-button" onClick={() => setRevision(n => n + 1)} aria-label="Refresh support and status information"><RefreshCw size={15} /></button></div><div className="help-contact-grid">
    <article><MessageCircle size={23} strokeWidth={1.4} /><h2>Need a hand?</h2>{errors.links ? <p role="alert">{errors.links}</p> : !config ? <p role="status">Checking support channels…</p> : config.supportUrl ? <><p>Join our official support server to chat with the community.</p><a className="text-link" href={config.supportUrl} target="_blank" rel="noreferrer">Open Support Server <ArrowUpRight size={16} /></a></> : <p>Our official support channel is being prepared. You can start with the FAQs above or try the interactive demo.</p>}</article>
    <article><Leaf size={23} strokeWidth={1.4} /><h2>Garden Status</h2>{errors.status ? <p role="alert">{errors.status}</p> : !status ? <p role="status">Checking status…</p> : <><p className={`help-service-state ${status.status === 'ok' ? 'state-ok' : ''}`}><span />{labels[status.status]}</p>{status.status !== 'unconfigured' && <><p className="small-note">Storage: {componentLabels[status.database]}. Topic worker: {componentLabels[status.worker]}.</p><p className="small-note">Checked at {new Date(status.checkedAt).toLocaleString('en-US')}. Does not verify Discord connection.</p></>}</>}</article>
  </div></section>;
}

function Guide() {
  const [query, setQuery] = useState('');
  const reduced = useReducedMotion();
  const items = faqs.filter(item => matchesText(`${item.question} ${item.answer}`, query));
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' });
  return <PublicLayout active="/guide" title="Guide & FAQ">
    <PageIntro eyebrow="GUIDE & FAQ" title={<>Getting started with<br /><em>Coconerd.</em></>}>First steps for your server, answers to frequently asked questions, and where to find support.</PageIntro>
    <nav className="help-jump-links" aria-label="Guide navigation"><button onClick={() => jump('help-start')}>Getting Started <ArrowDown size={13} /></button><button onClick={() => jump('help-questions')}>Frequently Asked Questions <ArrowDown size={13} /></button><button onClick={() => jump('help-contact')}>Support & Status <ArrowDown size={13} /></button></nav>
    <section className="help-start" id="help-start"><span className="eyebrow lime">01 / FOR YOUR SERVER</span><h2>Three steps, then just chat.</h2><div className="help-steps">
      <article><span className="help-step-number">01</span><h3>Add a companion.</h3><p>When official invites open, choose a server where you have administrative permissions to add Coconerd.</p><a href="#/invite" className="text-link">Check invitation <ArrowUpRight size={15} /></a></article>
      <article><span className="help-step-number">02</span><h3>Choose where the bot listens.</h3><p>Administrators authorize specific channels for message processing and inform members about the monitored scope.</p><a href="#/privacy" className="text-link">Learn about data & privacy <ArrowUpRight size={15} /></a></article>
      <article><span className="help-step-number">03</span><h3>Chat naturally as always.</h3><p>Coconerd connects related messages. When returning, read topics and digests to get back in sync.</p><a href="#/demo" className="text-link">Try the demo workspace <ArrowUpRight size={15} /></a></article>
    </div></section>
    <section className="help-faq" id="help-questions"><div className="help-faq-heading"><span className="eyebrow lime">02 / FREQUENTLY ASKED QUESTIONS</span><h2>Have questions?<br />We have answers.</h2><label className="public-search"><Search size={17} /><input aria-label="Search questions…" placeholder="Search questions…" value={query} onChange={event => setQuery(event.target.value)} />{query && <button onClick={() => setQuery('')} aria-label="Clear search">×</button>}</label><p className="result-count" aria-live="polite">{items.length} {items.length === 1 ? 'answer' : 'answers'}</p></div><div className="public-faq">{items.length ? items.map(item => <details key={item.question} open={query.trim() ? true : undefined}><summary>{item.question}<ChevronDown size={17} /></summary><p>{item.answer}</p></details>) : <div className="public-empty"><p>No matching answers found.</p><button className="text-link" onClick={() => setQuery('')}>View all questions <ArrowRight size={15} /></button></div>}</div></section>
    <HelpAvailability />
  </PublicLayout>;
}

function Privacy() {
  return <PublicLayout active="/privacy" title="Data & Privacy"><PageIntro eyebrow="CLEAR SCOPE, INTENTIONAL CHOICES" title={<>Data &<br /><em>Privacy.</em></>}>What Coconerd processes, where, and for how long. Here is what your community needs to know.</PageIntro><div className="privacy-article">{[
    ['Only Authorized Channels', 'The system ingests messages only from enabled servers and channels explicitly allowed by administrators. Administrators control this scope and can pause ingestion at any time. Direct messages (DMs) are never processed.'],
    ['Stored Information', 'Conversational data includes server ID, channel ID, message ID, author ID, display name, text content, timestamp, and reply references. Topics, summaries, and bot action tasks are retained to maintain conversation continuity.'],
    ['AI and Context', 'When live AI models are enabled, selected message content and context are sent to the configured AI service provider. Administrators should select appropriate channels and inform members. Summaries may not be exhaustive; always refer back to original messages.'],
    ['Retention Periods', 'Administrators can configure data retention from 1 to 3,650 days. Scheduled background workers prune expired records. Members should consult their server administrator regarding the active retention policy.'],
    ['Website and Demo Workspace', 'This website does not require user accounts and never displays private Discord server conversations. Content in the demo is purely simulated; changes are stored locally in your browser and can be reset anytime. The site uses Google Fonts for typography and contains no ads or third-party analytics.'],
  ].map(([title, copy], index) => <section key={title}><span>0{index + 1}</span><div><h2>{title}</h2><p>{copy}</p></div></section>)}</div></PublicLayout>;
}

export default function PublicPages({ route }: { route: string }) {
  if (route === '/features') return <Features />;
  if (route === '/guide') return <Guide />;
  if (route === '/privacy') return <Privacy />;
  return <PublicLayout active="" title="Page Not Found"><div className="public-empty"><Flower size={64} /><h1>Lost in a quiet corner of the garden?</h1><p>This page does not exist.</p><a className="pill" href="#/">Back to home <ArrowRight size={16} /></a></div></PublicLayout>;
}
