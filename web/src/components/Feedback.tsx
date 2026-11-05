import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react';
export function Loading({ label = 'Đang chăm chút không gian…' }: { label?: string }) { return <div className="loading" role="status"><LoaderCircle className="spin" size={24} /><span>{label}</span></div>; }
export function ErrorState({ error, retry }: { error: string; retry?: () => void }) { return <div className="error-state" role="alert"><AlertCircle size={22} /><div><strong>Chưa thể tải dữ liệu</strong><p>{error}</p>{retry && <button type="button" className="text-button" onClick={retry}><RefreshCw size={14} />Thử lại</button>}</div></div>; }
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Có lỗi xảy ra. Vui lòng thử lại.';
export function timeAgo(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).getTime()) / 60_000));
  return minutes < 1 ? 'Vừa xong' : minutes < 60 ? `${minutes} phút trước` : minutes < 1440 ? `${Math.floor(minutes / 60)} giờ trước` : `${Math.floor(minutes / 1440)} ngày trước`;
}
