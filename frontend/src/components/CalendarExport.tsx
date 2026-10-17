import { useState } from 'react';
import { usePortal } from '../context';
import { errorMessage } from '../lib/api';
import { t } from '../lib/i18n';
import { Icon, Modal } from './ui';

export function CalendarExport({ start, end, scope, month }: { start: string; end: string; scope: 'mine' | 'team'; month: string }) {
  const { api, mode } = usePortal();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [downloaded, setDownloaded] = useState(false);
  async function download() {
    if (busy) return;
    setBusy(true); setError(''); setDownloaded(false);
    try {
      const file = await api.getCalendarExport({ scope, start_date: start, end_date: end });
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url; link.download = `janapost-${scope}-${start.slice(0, 7)}.ics`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloaded(true);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <>
    <button className="btn btn-secondary" onClick={() => { setOpen(true); setError(''); setDownloaded(false); }}><Icon name="download" size={17}/>{t('Экспорт в Google Calendar')}</button>
    {open && <Modal title={t('Экспорт в Google Calendar')} onClose={() => setOpen(false)}>
      <p><strong>{month}</strong> · {t(scope === 'mine' ? 'Мой календарь' : 'Команда')}</p>
      <p>{t('В файл попадут только согласованные отпуска из выбранного календаря, пересекающие этот месяц. Даты каждого отпуска сохраняются целиком.')}</p>
      <ol className="cal-export-steps"><li>{t('Скачайте файл .ics.')}</li><li>{t('На компьютере откройте Google Calendar → Настройки → Импорт и экспорт.')}</li><li>{t('Выберите файл, целевой календарь и нажмите «Импорт».')}</li></ol>
      <p className="muted">{t('Это ручной перенос, без автоматической синхронизации. Изменения и отмены в портале не обновляют Google Calendar. Исправляйте импортированные события вручную; повторный импорт может создать дубликаты.')}</p>
      {mode === 'demo' ? <p role="status">{t('Общий экспорт доступен после входа в портал.')}</p> : <button className="btn btn-primary" disabled={busy} onClick={() => void download()}><Icon name="download" size={17}/>{t(busy ? 'Подготавливаем файл…' : 'Скачать календарь (.ics)')}</button>}
      {downloaded && <p role="status">{t('Файл скачан. Теперь импортируйте его в Google Calendar. Если согласованных отпусков за месяц нет, календарь будет пустым.')}</p>}
      {error && <p className="support-inline-error" role="alert">{error}</p>}
    </Modal>}
  </>;
}
