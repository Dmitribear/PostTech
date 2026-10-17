import { t } from '@/shared/lib/i18n';
import { useRef, useState } from 'react';

export function useListPage<T>(rows: T[], filterKey: string, size = 12) {
  const [state, setState] = useState({ key: filterKey, page: 0 });
  if (state.key !== filterKey) setState({ key: filterKey, page: 0 });
  const anchor = useRef<HTMLDivElement>(null);
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const page = state.key === filterKey ? Math.min(state.page, pages - 1) : 0;
  const change = (value: number) => {
    setState({ key: filterKey, page: Math.max(0, Math.min(value, pages - 1)) });
    anchor.current?.scrollIntoView({ block: 'start' });
  };
  return {
    items: rows.slice(page * size, (page + 1) * size),
    page,
    pages,
    change,
    anchor,
  };
}

export function ListPager({
  page,
  pages,
  change,
}: {
  page: number;
  pages: number;
  change: (page: number) => void;
}) {
  if (pages <= 1) return null;
  return (
    <nav className="list-pager" aria-label={t('Страницы списка')}>
      <button
        type="button"
        className="btn btn-secondary"
        disabled={page === 0}
        onClick={() => change(page - 1)}
      >
        {t('Назад')}
      </button>
      <span aria-live="polite">
        {page + 1} / {pages}
      </span>
      <button
        type="button"
        className="btn btn-secondary"
        disabled={page === pages - 1}
        onClick={() => change(page + 1)}
      >
        {t('Далее')}
      </button>
    </nav>
  );
}
