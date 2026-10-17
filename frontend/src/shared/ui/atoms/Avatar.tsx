import { tx } from '@/shared/lib/i18n';
export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  return (
    <span
      className="avatar"
      style={{ width: size, height: size, fontSize: size * 0.34 }}
      aria-hidden="true"
    >
      {tx(
        name
          .split(' ')
          .filter(Boolean)
          .slice(0, 2)
          .map((n) => n[0])
          .join(''),
      )}
    </span>
  );
}
