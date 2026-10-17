import { useState } from 'react';
import { usePortal } from '@/entities/session';
import type { AppRole, EmployeeProfile } from '@/shared/api/contracts';
import { errorMessage } from '@/shared/api/api';
import { t } from '@/shared/lib/i18n';

const roles: Record<AppRole, string> = {
  worker: 'Сотрудник',
  manager: 'Руководитель',
  director: 'Директор',
  hr_admin: 'HR-администратор',
};

export function AssignRole({
  employee,
  onSaved,
}: {
  employee: EmployeeProfile;
  onSaved: () => void;
}) {
  const { api, profile, refresh, notify } = usePortal();
  const [role, setRole] = useState<AppRole>(employee.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (profile.role !== 'hr_admin') return null;
  async function save() {
    if (busy || role === employee.role) return;
    setBusy(true);
    setError('');
    try {
      await api.assignEmployeeRole(employee.id, role);
      refresh();
      notify('Роль обновлена');
      onSaved();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="support-assign-form"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <label className="field">
        {t('Роль в системе')}
        <select
          className="input"
          value={role}
          disabled={busy || employee.id === profile.id}
          onChange={(event) => setRole(event.target.value as AppRole)}
        >
          {Object.entries(roles).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" className="support-inline-error">
          {error}
        </p>
      )}
      {role !== employee.role && (
        <button className="btn btn-primary" disabled={busy}>
          {t(busy ? 'Сохраняем…' : 'Сохранить роль')}
        </button>
      )}
    </form>
  );
}
