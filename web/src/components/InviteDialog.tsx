import { useEffect, useState } from 'react';
import { ArrowUpRight, RefreshCw } from 'lucide-react';
import { Dialog } from './Dialog';
import { request } from '../data/api';
import { errorMessage } from './Feedback';
import type { SiteConfig } from '../types';

export function InviteDialog({ onClose }: { onClose: () => void }) {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setConfig(null); setError('');
    void request<SiteConfig>('/api/site').then(result => {
      if (active) setConfig(result);
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [revision]);

  return <Dialog title="Add Coconerd to Discord" onClose={onClose}>
    <div className="invite-dialog-content">
      <img src="/assets/coconerd-bot.png" alt="" width={1254} height={1254} />
      <span className="eyebrow lime">A FRIEND FOR YOUR SERVER</span>
      <h2>{config?.inviteUrl ? 'Make a spot for Coconerd.' : 'See you on Discord.'}</h2>
      {error ? <><p role="alert">{error}</p><button className="button secondary" onClick={() => setRevision(n => n + 1)}><RefreshCw size={15} />Retry</button></> : !config ? <p role="status">Checking invitation…</p> : config.inviteUrl ? <><p>Choose a server where you have administrative permissions to add the bot.</p><a className="pill" href={config.inviteUrl} target="_blank" rel="noreferrer">Add to Discord <ArrowUpRight size={16} /></a></> : <><p>Official invite link is being prepared.<br />You can try Coconerd right now in the demo workspace.</p><a className="pill" href="#/demo">Explore Interactive Demo <ArrowUpRight size={16} /></a></>}
    </div>
  </Dialog>;
}
