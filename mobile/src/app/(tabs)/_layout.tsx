import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { api, type Approval } from '@/lib/api';
import { BadgeContext } from '@/lib/badge';
import { fonts, useTheme } from '@/lib/theme';

type Icon = keyof typeof Ionicons.glyphMap;
const icon = (on: Icon, off: Icon) => ({ color, focused }: { color: unknown; focused: boolean }) => (
  <Ionicons name={focused ? on : off} color={color as string} size={23} />
);

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
          tabBarActiveTintColor: t.text,
          tabBarInactiveTintColor: t.muted,
          tabBarStyle: { backgroundColor: t.bg, borderTopWidth: 0, elevation: 0, height: 64, paddingTop: 6 },
          tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 11, marginBottom: 4 },
          tabBarBadgeStyle: { backgroundColor: t.marigold, color: t.onAccent, fontFamily: fonts.semibold, fontSize: 10.5, minWidth: 17, height: 17, lineHeight: 15 },
        }}>
        <Tabs.Screen name="index" options={{ title: 'Today', tabBarIcon: icon('sunny', 'sunny-outline') }} />
        <Tabs.Screen name="chat" options={{ title: 'Chat', tabBarIcon: icon('chatbubble', 'chatbubble-outline') }} />
        <Tabs.Screen name="agent" options={{ title: 'Do it', tabBarIcon: icon('flash', 'flash-outline') }} />
        <Tabs.Screen name="approvals" options={{ title: 'Approvals', tabBarBadge: count ? count : undefined, tabBarIcon: icon('checkmark-circle', 'checkmark-circle-outline') }} />
        <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: icon('ellipsis-horizontal-circle', 'ellipsis-horizontal-circle-outline') }} />
      </Tabs>
    </BadgeContext.Provider>
  );
}
