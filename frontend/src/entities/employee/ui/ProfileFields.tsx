import type { EmployeeProfile } from '@/shared/api/contracts';
import { formatDate, roleLabels } from '@/shared/lib/format';
import { tx } from '@/shared/lib/i18n';
import '@/shared/styles/support.css';

export function ProfileFields({
  profile,
  section,
}: {
  profile: EmployeeProfile;
  section?: 'personal' | 'work';
}) {
  const personal = [
    ['ФИО', profile.full_name],
    ['Табельный номер', profile.employee_code],
    ['Рабочая почта', profile.email],
  ];
  const work = [
    ['Компания', profile.company],
    ['Должность', profile.job_title],
    ['Подразделение', profile.department],
    [
      'Руководитель',
      profile.manager_name ||
        (profile.manager_id ? 'Указан в кадровой системе' : 'Не назначен · согласует HR'),
    ],
    ['Дата приёма', formatDate(profile.hired_at)],
    ['Роль в портале', roleLabels[profile.role]],
  ];
  const fields =
    section === 'personal' ? personal : section === 'work' ? work : [...personal, ...work];
  return (
    <dl className="support-details-grid">
      {tx(
        fields.map(([title, value]) => (
          <div key={title}>
            <dt>{tx(title)}</dt>
            <dd>{tx(value || 'Не указано')}</dd>
          </div>
        )),
      )}
    </dl>
  );
}
