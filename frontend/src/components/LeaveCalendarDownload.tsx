import { useState } from 'react';
import { usePortal } from '../context';
import { errorMessage } from '../lib/api';
import { Icon } from './ui';

export function LeaveCalendarDownload({ requestId }: { requestId: string }) {
  const { api, mode } = usePortal();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function download() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const file = await api.getLeaveCalendar(requestId);
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${mode === 'demo' ? 'demo-' : ''}leave-${requestId}.ics`;
      document.body.appendChild(link); link.click(); link.remove();
      // Let the browser start reading before releasing the object URL.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <section className="card req-form-card">
    <div className="req-card-heading"><h2><Icon name="calendar" size={20} />Google Calendar</h2></div>
    <p>Скачайте файл отпуска и импортируйте его в Google Calendar на компьютере: «Настройки» → «Импорт и экспорт» → «Импорт».</p>
    <p className="muted">Импорт выполняется вручную. При переносе или отмене отпуска измените событие в календаре самостоятельно.{mode === 'demo' && ' Файл содержит вымышленные демонстрационные даты.'}</p>
    <button className="btn btn-secondary" disabled={busy} onClick={() => void download()}><Icon name="download" size={17} />{busy ? 'Подготавливаем файл…' : 'Скачать отпуск (.ics)'}</button>
    {error && <p className="support-inline-error" role="alert">{error}</p>}
  </section>;
}
