import { createContext, useContext } from 'react';

/** The approvals count shown on the tab bar, refreshable from any screen. */
export const BadgeContext = createContext<{ count: number; refresh: () => Promise<void> }>({
  count: 0,
  refresh: async () => {},
});

export const useBadge = () => useContext(BadgeContext);
