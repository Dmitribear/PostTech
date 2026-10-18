import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import type { CourseAssignment, PersonalCourseInput } from '@/shared/api/contracts';
import { t } from '@/shared/lib/i18n';
import { Modal } from '@/shared/ui';
import { useRef, useState, type FormEvent } from 'react';

export function PersonalCourseForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (assignment: CourseAssignment) => void;
}) {
  const { api, notify, refresh } = usePortal();
  const [input, setInput] = useState<PersonalCourseInput>({
    id: crypto.randomUUID(),
    title: '',
    provider: '',
    external_url: '',
    due_on: '',
    progress_percent: 0,
  });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current || (input.progress_percent === 100 && !confirmed)) return;
    let url: URL;
    try {
      url = new URL(input.external_url.trim());
    } catch {
      setError(t('Укажите ссылку на курс, начиная с https://'));
      return;
    }
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      /[\s\\]/.test(input.external_url.trim())
    ) {
      setError(t('Укажите ссылку на курс, начиная с https://'));
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const assignment = await api.createPersonalCourse({
        ...input,
        title: input.title.trim(),
        provider: input.provider.trim(),
        external_url: input.external_url.trim(),
      });
      refresh();
      notify(t('Курс добавлен в моё обучение'));
      onCreated(assignment);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal
      title={t('Свой курс')}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="personal-course-form" onSubmit={submit}>
        <p className="muted">
          {t(
            'Добавьте обучение на внешней площадке. Руководитель и HR увидят срок и ваш прогресс.',
          )}
        </p>
        <label className="field">
          {t('Ссылка на курс')}
          <input
            className="input"
            type="url"
            required
            maxLength={2000}
            placeholder="https://"
            value={input.external_url}
            disabled={busy}
            onChange={(e) => setInput({ ...input, external_url: e.target.value })}
          />
        </label>
        <label className="field">
          {t('Название курса')}
          <input
            className="input"
            required
            minLength={3}
            maxLength={200}
            value={input.title}
            disabled={busy}
            onChange={(e) => setInput({ ...input, title: e.target.value })}
          />
        </label>
        <label className="field">
          {t('Площадка')}
          <input
            className="input"
            required
            maxLength={160}
            placeholder={t('Например, Яндекс Практикум')}
            value={input.provider}
            disabled={busy}
            onChange={(e) => setInput({ ...input, provider: e.target.value })}
          />
        </label>
        <div className="personal-course-dates">
          <label className="field">
            {t('Пройти до')}
            <input
              className="input"
              type="date"
              required
              value={input.due_on}
              disabled={busy}
              onChange={(e) => setInput({ ...input, due_on: e.target.value })}
            />
          </label>
          <label className="field">
            {t('Пройдено, %')}
            <input
              className="input"
              type="number"
              required
              min={0}
              max={100}
              step={1}
              value={Number.isNaN(input.progress_percent) ? '' : input.progress_percent}
              disabled={busy}
              onChange={(e) => {
                setInput({ ...input, progress_percent: e.target.valueAsNumber });
                setConfirmed(false);
              }}
            />
          </label>
        </div>
        {input.progress_percent === 100 && (
          <label className="external-completion">
            <input
              type="checkbox"
              required
              disabled={busy}
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>{t('Я завершил курс на площадке')}</span>
          </label>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn-primary" disabled={busy}>
          {t(busy ? 'Сохраняем…' : 'Добавить курс')}
        </button>
      </form>
    </Modal>
  );
}
