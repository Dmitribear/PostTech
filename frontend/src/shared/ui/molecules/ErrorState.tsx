import { errorMessage } from '@/shared/api/api';
import { t, tx } from '@/shared/lib/i18n';
import { Icon } from '../atoms/Icon';
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <Icon name="alert" />
      <div>
        <strong>{t('Не удалось загрузить данные')}</strong>
        <p>{tx(errorMessage(error))}</p>
        {tx(
          retry && (
            <button className="btn btn-secondary" onClick={retry}>
              <Icon name="refresh" size={16} />
              {t('Повторить')}
            </button>
          ),
        )}
      </div>
    </div>
  );
}
