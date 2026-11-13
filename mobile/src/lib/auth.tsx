import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, setSessionToken, setUnauthorizedHandler, tokenStore, type Me } from './api';

type AuthState = {
  loading: boolean;
  token: string | null;
  me: Me | null;
  signIn: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<Me | null>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);

  const forget = useCallback(async () => {
    await tokenStore.clear();
    setSessionToken(null);
    setToken(null);
    setMe(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const m = await api<Me>('/me');
      setMe(m);
      return m;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { void forget(); });
    (async () => {
      const t = await tokenStore.get();
      if (t) {
        setSessionToken(t);
        setToken(t);
        const m = await refresh();
        if (!m) await forget();
      }
      setLoading(false);
    })();
  }, [forget, refresh]);

  const signIn = useCallback(async (t: string) => {
    await tokenStore.set(t);
    setSessionToken(t);
    setToken(t);
    await refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try {
      const { unregisterPush } = await import('./push');
      await unregisterPush();
      await api('/logout/app', { method: 'POST' });
    } catch {}
    await forget();
  }, [forget]);

  const value = useMemo(() => ({ loading, token, me, signIn, signOut, refresh }), [loading, token, me, signIn, signOut, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
