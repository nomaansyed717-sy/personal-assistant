import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { api, type Approval } from '@/lib/api';
import { BadgeContext } from '@/lib/badge';
import { useTheme } from '@/lib/theme';

export default function TabLayout() {
  const t = useTheme();
  const [count, setCount] = useState(0);
  const refresh = async () => {
    try { setCount((await api<Approval[]>('/approvals')).length); } catch {}
  };

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 20000);
    const sub = AppState.addEventListener('change', s => { if (s === 'active') void refresh(); });
    return () => { clearInterval(id); sub.remove(); };
  }, []);

  return (
    <BadgeContext.Provider value={{ count, refresh }}>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarActiveTintColor: t.ink2,
          tabBarInactiveTintColor: t.muted,
          tabBarStyle: { backgroundColor: t.card, borderTopColor: t.line },
          tabBarBadgeStyle: { backgroundColor: t.marigold, color: '#2B1C02', fontWeight: '700' },
        }}>
        <Tabs.Screen name="index" options={{ title: 'Today', tabBarIcon: ({ color, size }) => <Ionicons name="sunny-outline" color={color as string} size={size} /> }} />
        <Tabs.Screen name="chat" options={{ title: 'Chat', tabBarIcon: ({ color, size }) => <Ionicons name="chatbubble-ellipses-outline" color={color as string} size={size} /> }} />
        <Tabs.Screen name="agent" options={{ title: 'Do it', tabBarIcon: ({ color, size }) => <Ionicons name="flash-outline" color={color as string} size={size} /> }} />
        <Tabs.Screen
          name="approvals"
          options={{
            title: 'Approvals',
            tabBarBadge: count ? count : undefined,
            tabBarIcon: ({ color, size }) => <Ionicons name="checkmark-done-outline" color={color as string} size={size} />,
          }}
        />
        <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: ({ color, size }) => <Ionicons name="grid-outline" color={color as string} size={size} /> }} />
      </Tabs>
    </BadgeContext.Provider>
  );
}
