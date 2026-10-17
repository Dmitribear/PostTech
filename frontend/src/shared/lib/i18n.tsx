import translations from '@/shared/lib/kk.json';
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
} from 'react';

export type Locale = 'ru' | 'kk';
let locale: Locale = 'ru';
try {
  locale = localStorage.getItem('posttech.locale') === 'kk' ? 'kk' : 'ru';
} catch {
  /* private mode */
}
if (typeof document !== 'undefined') document.documentElement.lang = locale;
const listeners = new Set<() => void>();
const dictionary: Record<string, string> = translations;
const templates = Object.entries(dictionary)
  .filter(([key]) => /\{\d+\}/.test(key))
  .map(([key, value]) => ({
    pattern: new RegExp(
      '^' +
        key
          .split(/\{\d+\}/)
          .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
          .join('(.*?)') +
        '$',
    ),
    value,
  }));
export function getLocale() {
  return locale;
}
export function setLocale(value: Locale) {
  locale = value;
  try {
    localStorage.setItem('posttech.locale', value);
  } catch {}
  if (typeof document !== 'undefined') document.documentElement.lang = value;
  listeners.forEach((fn) => fn());
}
export function useLocale() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    getLocale,
    () => 'ru' as Locale,
  );
}
/** Exact UI catalogue matching. User-authored prose is never machine translated. */
export function t(value: string): string {
  if (locale === 'ru') return value;
  const key = value.trim().replace(/\s+/g, ' ');
  const translated = dictionary[key];
  if (translated) return value.replace(value.trim(), translated);
  for (const template of templates) {
    const match = key.match(template.pattern);
    if (match)
      return value.replace(
        value.trim(),
        template.value.replace(/\{(\d+)\}/g, (_, i) => match[Number(i) + 1]),
      );
  }
  return value;
}
export function tx<T>(value: T): T {
  return (
    typeof value === 'string'
      ? t(value)
      : Array.isArray(value)
        ? value.map((v) => (typeof v === 'string' ? t(v) : v))
        : value
  ) as T;
}
export function LanguageSwitch() {
  const current = useLocale();
  const [open, setOpen] = useState(false);
  const optionsId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<Array<HTMLButtonElement | null>>([]);
  const values: Locale[] = ['ru', 'kk'];
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onFocus = (event: FocusEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('focusin', onFocus);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('focusin', onFocus);
    };
  }, [open]);
  function choose(value: Locale) {
    setLocale(value);
    setOpen(false);
    trigger.current?.focus();
  }
  function onOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = (index + 1) % values.length;
    const previous = (index + values.length - 1) % values.length;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      event.preventDefault();
      options.current[next]?.focus();
    } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
      event.preventDefault();
      options.current[previous]?.focus();
    } else if (event.key === 'Home') {
      event.preventDefault();
      options.current[0]?.focus();
    } else if (event.key === 'End') {
      event.preventDefault();
      options.current[values.length - 1]?.focus();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      trigger.current?.focus();
    } else if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      choose(values[index]);
    }
  }
  return (
    <div className="language-picker" ref={root}>
      <button
        ref={trigger}
        className="language-switch"
        type="button"
        aria-label="Language / Тіл"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={optionsId}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !open) {
            event.preventDefault();
            setOpen(true);
            requestAnimationFrame(() => options.current[values.indexOf(current)]?.focus());
          } else if (event.key === 'Escape' && open) {
            event.preventDefault();
            setOpen(false);
          }
        }}
      >
        <span>{current === 'ru' ? 'RU' : 'KZ'}</span>
        <span className="language-chevron" aria-hidden="true" />
      </button>
      {open && (
        <div id={optionsId} className="language-options" role="listbox" aria-label="Language / Тіл">
          {values.map((value, index) => (
            <button
              ref={(node) => {
                options.current[index] = node;
              }}
              key={value}
              type="button"
              role="option"
              aria-selected={current === value}
              className={`language-option ${current === value ? 'selected' : ''}`}
              onClick={() => choose(value)}
              onKeyDown={(event) => onOptionKeyDown(event, index)}
            >
              {value === 'ru' ? 'Русский' : 'Қазақша'}
              <span>{value === 'ru' ? 'RU' : 'KZ'}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Embedded browsers may omit Kazakh ICU month names; never show M01/M10. */
export function localizedDate(date: Date, options: Intl.DateTimeFormatOptions = {}): string {
  if (locale === 'ru') return new Intl.DateTimeFormat('ru-RU', options).format(date);
  const months = [
    'қаңтар',
    'ақпан',
    'наурыз',
    'сәуір',
    'мамыр',
    'маусым',
    'шілде',
    'тамыз',
    'қыркүйек',
    'қазан',
    'қараша',
    'желтоқсан',
  ];
  const parts = new Intl.DateTimeFormat('en-GB', {
    ...options,
    ...(options.month ? { month: 'numeric' } : {}),
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value;
  const result = [];
  if (get('weekday'))
    result.push(
      (
        {
          Monday: 'дүйсенбі',
          Tuesday: 'сейсенбі',
          Wednesday: 'сәрсенбі',
          Thursday: 'бейсенбі',
          Friday: 'жұма',
          Saturday: 'сенбі',
          Sunday: 'жексенбі',
          Mon: 'дс',
          Tue: 'сс',
          Wed: 'ср',
          Thu: 'бс',
          Fri: 'жм',
          Sat: 'сб',
          Sun: 'жс',
        } as Record<string, string>
      )[get('weekday')!] || get('weekday'),
    );
  if (options.day && get('day')) result.push(get('day'));
  if (options.month && get('month'))
    result.push(
      ['numeric', '2-digit'].includes(options.month)
        ? get('month')
        : months[Number(get('month')) - 1],
    );
  if (options.year && get('year')) result.push(get('year'));
  if (get('hour'))
    result.push([get('hour'), get('minute'), get('second')].filter(Boolean).join(':'));
  return result.join(' ');
}
