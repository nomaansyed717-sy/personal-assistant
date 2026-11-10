import Ionicons from '@expo/vector-icons/Ionicons';
import { router, type Href } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Screen, Title } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

const ITEMS: { href: Href; icon: keyof typeof Ionicons.glyphMap; title: string; sub: string }[] = [
  { href: '/activity', icon: 'time-outline', title: 'Activity', sub: 'What it did and what it plans to do' },
  { href: '/goals', icon: 'flag-outline', title: 'Goals', sub: 'What it works toward with you' },
  { href: '/tasks', icon: 'repeat-outline', title: 'Standing tasks', sub: 'Price watches, slot checks, chasers' },
  { href: '/memory', icon: 'bulb-outline', title: 'Memory', sub: 'What it knows about you' },
  { href: '/skills', icon: 'construct-outline', title: 'Skills', sub: 'Routines it can run for you' },
  { href: '/money', icon: 'wallet-outline', title: 'Money', sub: 'Subscriptions and recurring charges' },
  { href: '/vault', icon: 'lock-closed-outline', title: 'Vault', sub: 'Logins only the secure browser can use' },
  { href: '/settings', icon: 'settings-outline', title: 'Settings', sub: 'Name, personality, brief time, account' },
];

export default function More() {
  const t = useTheme();
  const { me, signOut } = useAuth();
  return (
    <Screen>
      <Title sub={me?.demo ? 'Live demo account' : me?.email || me?.phone || undefined}>More</Title>
      <View style={[styles.group, { backgroundColor: t.card, borderColor: t.line }]}>
        {ITEMS.map((it, i) => (
          <Pressable
            key={it.title}
            accessibilityRole="button"
            onPress={() => router.push(it.href)}
            style={({ pressed }) => [styles.item, i > 0 && { borderTopWidth: 1, borderTopColor: t.line }, pressed && { opacity: 0.7 }]}>
            <Ionicons name={it.icon} size={22} color={t.ink2} />
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>{it.title}</Text>
              <Text style={{ color: t.muted, fontSize: 13 }}>{it.sub}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={t.muted} />
          </Pressable>
        ))}
      </View>
      <Pressable accessibilityRole="button" onPress={signOut} style={[styles.item, styles.group, { backgroundColor: t.card, borderColor: t.line, marginTop: space.l }]}>
        <Ionicons name="log-out-outline" size={22} color={t.rose} />
        <Text style={{ color: t.rose, fontSize: 16, fontWeight: '600' }}>{me?.demo ? 'End the demo' : 'Sign out'}</Text>
      </Pressable>
    </Screen>
  );
}

const styles = StyleSheet.create({
  group: { borderWidth: 1, borderRadius: radius.m, overflow: 'hidden' },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.m, paddingHorizontal: space.l, paddingVertical: space.m + 2 },
});
