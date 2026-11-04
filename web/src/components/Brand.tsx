export function Flower({ className = '', size = 30 }: { className?: string; size?: number }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true"><g stroke="currentColor" strokeWidth="2.4"><ellipse cx="32" cy="32" rx="10" ry="26" /><ellipse cx="32" cy="32" rx="10" ry="26" transform="rotate(60 32 32)" /><ellipse cx="32" cy="32" rx="10" ry="26" transform="rotate(120 32 32)" /></g><circle cx="32" cy="32" r="4" fill="currentColor" /></svg>;
}
export function Brand({ light = false }: { light?: boolean }) { return <a className={`brand ${light ? 'brand-light' : ''}`} href="#/" aria-label="Coconerd — trang chủ"><Flower /><span>coconerd<span className="brand-dot">®</span></span></a>; }
