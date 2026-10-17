import type { HrApi } from '@/shared/api/api';
import type { EmployeeProfile } from '@/shared/api/contracts';
import { createContext, useContext } from 'react';

export interface PortalContextValue {
  api: HrApi;
  profile: EmployeeProfile;
  refreshKey: number;
  refresh: () => void;
  notify: (message: string) => void;
  mode: 'live' | 'demo';
  logout: () => void;
}
export const PortalContext = createContext<PortalContextValue | null>(null);
export function usePortal() {
  const value = useContext(PortalContext);
  if (!value) throw new Error('Portal context is missing');
  return value;
}
