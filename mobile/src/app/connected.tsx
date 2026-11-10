import { router } from 'expo-router';
import { useEffect } from 'react';

import { Loading } from '@/components/ui';
import { useAuth } from '@/lib/auth';

/** Landing spot for the aide://connected deep link after Google sign-in. */
export default function Connected() {
  const { refresh } = useAuth();
  useEffect(() => {
    void refresh().then(() => router.replace('/'));
  }, [refresh]);
  return <Loading />;
}
