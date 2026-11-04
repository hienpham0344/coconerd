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

  return <Dialog title="Thêm Coconerd vào Discord" onClose={onClose}>
    <div className="invite-dialog-content">
      <img src="/assets/coconerd-bot.png" alt="" width={1254} height={1254} />
      <span className="eyebrow lime">MỘT NGƯỜI BẠN CHO SERVER</span>
      <h2>{config?.inviteUrl ? 'Dành một chỗ cho Coconerd.' : 'Hẹn bạn ở Discord.'}</h2>
      {error ? <><p role="alert">{error}</p><button className="button secondary" onClick={() => setRevision(n => n + 1)}><RefreshCw size={15} />Thử lại</button></> : !config ? <p role="status">Đang kiểm tra lời mời…</p> : config.inviteUrl ? <><p>Chọn server bạn có quyền quản lý để thêm bot.</p><a className="pill" href={config.inviteUrl} target="_blank" rel="noreferrer">Thêm vào Discord <ArrowUpRight size={16} /></a></> : <><p>Link mời chính thức đang được chuẩn bị.<br />Bạn có thể thử Coconerd ngay trong không gian mẫu.</p><a className="pill" href="#/demo">Khám phá bản trải nghiệm <ArrowUpRight size={16} /></a></>}
    </div>
  </Dialog>;
}
