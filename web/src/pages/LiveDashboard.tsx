import { useEffect, useMemo, useState } from 'react';
import { LogIn } from 'lucide-react';
import Dashboard from './Dashboard';
import { ApiError, request } from '../data/api';
import { liveClient, privateRequest } from '../data/live';
import { ErrorState, Loading, errorMessage } from '../components/Feedback';
import { PublicLayout } from '../components/PublicLayout';
import type { LoginSession } from '../types';

export default function LiveDashboard({ route }: { route: string }) {
  const [session, setSession] = useState<LoginSession | null>(null);
  const [busy, setBusy] = useState(true); const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const api = useMemo(() => liveClient(session?.csrfToken || ''), [session?.csrfToken]);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(''); setSession(null);
    void request<LoginSession>('/api/auth/session', { cache: 'no-store' }).then(value => {
      if (active) setSession(value);
    }).catch(e => { if (active && !(e instanceof ApiError && e.status === 401)) setError(errorMessage(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [revision]);
  useEffect(() => {
    const denied = (event: Event) => {
      const code = (event as CustomEvent<number>).detail;
      setSession(null); setError(code === 403 ? 'Quyền quản trị server đã thay đổi. Vui lòng tải lại danh sách server.' : 'Phiên đăng nhập đã hết hạn.');
      if (code === 403) location.hash = '/app';
    };
    window.addEventListener('coconerd-access-error', denied);
    return () => window.removeEventListener('coconerd-access-error', denied);
  }, []);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(() => { setSession(null); setError('Phiên đăng nhập đã hết hạn.'); }, Math.max(0, Date.parse(session.expiresAt) - Date.now()));
    return () => clearTimeout(timer);
  }, [session]);
  const logout = async () => {
    if (!session) return;
    try {
      await privateRequest('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.csrfToken } });
      setSession(null); location.hash = '/app';
    } catch (e) { setError(errorMessage(e)); }
  };
  if (busy) return <div className="full-loading"><Loading label="Đang kiểm tra phiên đăng nhập…" /></div>;
  if (!session) return <PublicLayout active="/app" title="Dashboard"><section className="login-panel">
    <span className="eyebrow lime">KHÔNG GIAN QUẢN TRỊ</span><h1>Chăm sóc những cuộc trò chuyện.</h1>
    <p>Đăng nhập bằng Discord để xem hội thoại, quản lý chủ đề và cấu hình Coconerd trong server bạn làm chủ hoặc có quyền Administrator.</p>
    {error && <ErrorState error={error} retry={() => setRevision(n => n + 1)} />}
    <a className="button primary" href="/auth/discord"><LogIn size={18} />Đăng nhập bằng Discord</a>
    <p className="small-note">Tài khoản thường không được xem dữ liệu hội thoại của server.</p>
  </section></PublicLayout>;
  return <>{error && <p className="form-error live-notice" role="alert">{error}</p>}<Dashboard key={session.user.id} route={route} mode="live" api={api} session={session} onLogout={() => void logout()} /></>;
}
