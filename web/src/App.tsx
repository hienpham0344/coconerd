import { lazy, Suspense, useEffect, useState } from 'react';
import { Landing } from './pages/Landing';
import { Loading } from './components/Feedback';
import { PageMotion } from './components/PageMotion';
import { InviteDialog } from './components/InviteDialog';
import { resolveNavigation } from './routes';
const Dashboard = lazy(() => import('./pages/Dashboard'));
const LiveDashboard = lazy(() => import('./pages/LiveDashboard'));
const PublicPages = lazy(() => import('./pages/PublicPages'));

export function App() {
  const [navigation, setNavigation] = useState(() => resolveNavigation(location.hash));
  useEffect(() => {
    const change = () => {
      const nextHash = location.hash;
      setNavigation(current => resolveNavigation(nextHash, current.route));
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => { if (navigation.resetScroll) window.scrollTo(0, 0); }, [navigation]);
  const { route } = navigation;
  return <><Suspense fallback={<div className="full-loading"><Loading /></div>}>
    <PageMotion route={route}>
      {route === '/' ? <Landing /> : /^\/app(?:\/|$)/.test(route) ? <LiveDashboard route={route} /> : /^\/demo(?:\/|$)/.test(route) ? <Dashboard route={route} /> : <PublicPages route={route} />}
    </PageMotion>
  </Suspense>{navigation.inviteOpen && <InviteDialog onClose={() => { location.hash = route; }} />}</>;
}
