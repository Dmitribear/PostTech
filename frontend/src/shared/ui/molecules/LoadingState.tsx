import { t } from '@/shared/lib/i18n';
export function LoadingState() {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" />
      {t('Загружаем данные…')}
    </div>
  );
}
