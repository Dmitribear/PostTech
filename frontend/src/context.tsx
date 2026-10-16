import { createContext, useContext } from 'react';
import type { HrApi } from './lib/api';
import type { EmployeeProfile } from './lib/types';

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
