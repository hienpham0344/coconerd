import { useEffect, useState, type FormEvent } from 'react';
import { Save } from 'lucide-react';
import { dashboardRequest } from '../data/live';
import { ErrorState, Loading, errorMessage } from './Feedback';
import type { Channel, Guild, ModelConfig } from '../types';

export function GuildSettings({ guildId, csrf, onChanged }: { guildId: string; csrf: string; onChanged: () => void }) {
  const [settings, setSettings] = useState<Guild | null>(null);
  const [model, setModel] = useState<ModelConfig | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(true); const [saving, setSaving] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true; setBusy(true); setError('');
    void Promise.all([
      dashboardRequest<Guild>(guildId, 'settings', csrf),
      dashboardRequest<ModelConfig>(guildId, 'model', csrf),
      dashboardRequest<{ items: Channel[] }>(guildId, 'channels', csrf),
    ]).then(([settings, model, channels]) => { if (active) { setSettings(settings); setModel(model); setChannels(channels.items); } })
      .catch(e => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [guildId, csrf, revision]);
  async function save(event: FormEvent, kind: 'settings' | 'model') {
    event.preventDefault(); if (!settings || !model) return;
    setSaving(kind); setError(''); setNotice('');
    const body = kind === 'settings' ? {
      enabled: settings.enabled, allowed_channel_ids: settings.allowed_channel_ids,
      output_channel_id: settings.output_channel_id || null, retention_days: settings.retention_days,
    } : { provider: 'meta', model_id: model.model_id, temperature: model.temperature, max_tokens: model.max_tokens };
    try {
      await dashboardRequest(guildId, kind, csrf, 'PUT', body);
      setNotice(kind === 'settings' ? 'Đã lưu cấu hình server.' : 'Đã lưu cấu hình AI cho server này.');
      onChanged();
    } catch (e) { setError(errorMessage(e)); } finally { setSaving(''); }
  }
  if (busy) return <Loading />;
  if (!settings || !model) return <ErrorState error={error || 'Chưa tải được cấu hình.'} retry={() => setRevision(n => n + 1)} />;
  return <div className="admin-settings">
    {error && <p className="form-error" role="alert">{error}</p>}
    {notice && <p className="save-notice" role="status">{notice}</p>}
    <form className="admin-panel admin-form" onSubmit={event => void save(event, 'settings')}>
      <h2>Cấu hình server</h2><fieldset disabled={!!saving}>
        <label className="check-line"><input type="checkbox" checked={settings.enabled} onChange={e => setSettings({ ...settings, enabled: e.target.checked })} />Nhận tin nhắn từ các kênh được chọn</label>
        <div><span className="field-label">Kênh đầu vào</span><div className="channel-options">
          {channels.map(channel => <label className="check-line" key={channel.id}><input type="checkbox" checked={settings.allowed_channel_ids.includes(channel.id)}
            onChange={e => setSettings({ ...settings, allowed_channel_ids: e.target.checked ? [...settings.allowed_channel_ids, channel.id] : settings.allowed_channel_ids.filter(id => id !== channel.id) })} />#{channel.name}</label>)}
          {!channels.length && <p>Bot chưa đọc được kênh văn bản nào trong server.</p>}
        </div></div>
        <label>Kênh đầu ra<select value={settings.output_channel_id || ''} onChange={e => setSettings({ ...settings, output_channel_id: e.target.value || null })}>
          <option value="">Chưa chọn</option>{channels.map(channel => <option key={channel.id} value={channel.id}>#{channel.name}</option>)}
        </select></label>
        {settings.output_channel_id && settings.allowed_channel_ids.includes(settings.output_channel_id) && <p className="form-error">Kênh đầu ra phải khác kênh đầu vào.</p>}
        <label>Thời hạn lưu tin nhắn (ngày)<input type="number" min={1} max={3650} required value={settings.retention_days} onChange={e => setSettings({ ...settings, retention_days: Number(e.target.value) })} /></label>
        <button className="button primary small" disabled={!!settings.output_channel_id && settings.allowed_channel_ids.includes(settings.output_channel_id)}><Save size={16} />{saving === 'settings' ? 'Đang lưu…' : 'Lưu cấu hình server'}</button>
      </fieldset>
    </form>
    <form className="admin-panel admin-form" onSubmit={event => void save(event, 'model')}>
      <h2>AI của server</h2><p className="small-note">Các giá trị này áp dụng riêng cho server đang chọn.</p>
      <fieldset disabled={!!saving}>
        <label>Model Meta<input required maxLength={200} value={model.model_id} onChange={e => setModel({ ...model, model_id: e.target.value })} /></label>
        <label>Temperature<input type="number" min={0} max={2} step={0.1} required value={model.temperature} onChange={e => setModel({ ...model, temperature: Number(e.target.value) })} /></label>
        <label>Giới hạn token trả lời<input type="number" min={1} max={32768} required value={model.max_tokens} onChange={e => setModel({ ...model, max_tokens: Number(e.target.value) })} /></label>
        <button className="button primary small"><Save size={16} />{saving === 'model' ? 'Đang lưu…' : 'Lưu cấu hình AI'}</button>
      </fieldset>
    </form>
  </div>;
}
