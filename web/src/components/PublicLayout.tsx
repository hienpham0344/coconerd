import { useEffect, useState, type ReactNode } from 'react';
import { ArrowUpRight, Menu, X } from 'lucide-react';
import { Brand, Flower } from './Brand';

const navigation = [
  ['Features', '/features'], ['Guide', '/guide'], ['Demo', '/demo'],
];

export function PublicHeader({ hero = false, active = '' }: { hero?: boolean; active?: string }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { setOpen(false); }, [active]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, []);
  return <header className={`public-header ${hero ? 'public-header-hero' : ''}`}>
    <Brand />
    <nav id="public-navigation" className={open ? 'public-nav is-open' : 'public-nav'} aria-label="Main navigation">
      {navigation.map(([label, href]) => <a key={href} href={`#${href}`} aria-current={active === href ? 'page' : undefined} onClick={() => setOpen(false)}>{label}</a>)}
      <a className="pill" href="#/invite" onClick={() => setOpen(false)}>Add to Discord <ArrowUpRight size={16} /></a>
    </nav>
    <button className="icon-button public-menu" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} aria-controls="public-navigation" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
  </header>;
}

export function PublicFooter() {
  return <footer className="public-footer section-shell">
    <div><Brand /><p>A little order. A lot more connection.</p></div>
    <div className="footer-links"><a href="#/features">Features</a><a href="#/guide">Guide & FAQ</a><a href="#/demo">Demo</a><a href="#/privacy">Data & Privacy</a></div>
    <div className="footer-bottom"><span>© {new Date().getFullYear()} Coconerd</span><span><Flower size={15} /> Good things grow together.</span></div>
  </footer>;
}

export function PublicLayout({ active, title, children }: { active: string; title: string; children: ReactNode }) {
  useEffect(() => { document.title = `${title} — Coconerd`; }, [title]);
  return <div className="public-page"><PublicHeader active={active} /><main className="public-main" id="page-content">{children}</main><PublicFooter /></div>;
}

export function PageIntro({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children: ReactNode }) {
  return <div className="public-intro"><span className="eyebrow lime">{eyebrow}</span><h1>{title}</h1><p>{children}</p><Flower className="intro-flower" size={200} /></div>;
}
