import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react';
export function Loading({ label = 'Preparing the space…' }: { label?: string }) { return <div className="loading" role="status"><LoaderCircle className="spin" size={24} /><span>{label}</span></div>; }
export function ErrorState({ error, retry }: { error: string; retry?: () => void }) { return <div className="error-state" role="alert"><AlertCircle size={22} /><div><strong>Unable to load data</strong><p>{error}</p>{retry && <button className="text-button" onClick={retry}><RefreshCw size={14} />Retry</button>}</div></div>; }
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'An error occurred. Please try again.';
export function timeAgo(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).getTime()) / 60_000));
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : `${Math.floor(minutes / 1440)}d ago`;
}
