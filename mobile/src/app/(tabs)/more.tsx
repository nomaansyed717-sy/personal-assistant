import Ionicons from '@expo/vector-icons/Ionicons';
import { router, type Href } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { Screen, Text, Title } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

type Item = { href: Href; icon: keyof typeof Ionicons.glyphMap; title: string; sub: string };
const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: 'Your assistant',
    items: [
      { href: '/activity', icon: 'time-outline', title: 'Activity', sub: 'What it did and plans to do' },
      { href: '/goals', icon: 'flag-outline', title: 'Goals', sub: 'What it works toward with you' },
      { href: '/tasks', icon: 'repeat-outline', title: 'Standing tasks', sub: 'Price watches, slot checks, chasers' },
      { href: '/automations', icon: 'git-network-outline', title: 'Automations', sub: 'When an email arrives or a webhook fires' },
      { href: '/skills', icon: 'sparkles-outline', title: 'Skills', sub: 'Routines it can run for you' },
      { href: '/apps', icon: 'apps-outline', title: 'Connected apps', sub: 'Notion, GitHub, Zapier and 8,000 more' },
    ],
  },
  {
    title: 'Your data',
    items: [
      { href: '/memory', icon: 'bulb-outline', title: 'Memory', sub: 'What it knows about you' },
      { href: '/money', icon: 'wallet-outline', title: 'Money', sub: 'Subscriptions and recurring charges' },
      { href: '/vault', icon: 'lock-closed-outline', title: 'Vault', sub: 'Logins only the secure browser can use' },
      { href: '/settings', icon: 'settings-outline', title: 'Settings', sub: 'Name, personality, brief time, account' },
    ],
  },
];

export default function More() {
  const t = useTheme();
  const { me, signOut } = useAuth();
  const who = me?.demo ? 'Live demo' : me?.email || me?.phone || '';
  return (
    <Screen>
      <Title>More</Title>

      <View style={[styles.profile, { backgroundColor: t.card, borderColor: t.line }]}>
        <View style={[styles.avatar, { backgroundColor: t.ink }]}>
          <Text style={{ color: t.onInk, fontWeight: '700', fontSize: 18 }}>{(me?.name || 'Y')[0].toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: t.text, fontSize: 16, fontWeight: '600' }}>{me?.name || 'You'}</Text>
          <Text style={{ color: t.muted, fontSize: 13 }}>{who}</Text>
        </View>
      </View>

      {GROUPS.map(g => (
        <View key={g.title}>
          <Text style={[styles.group, { color: t.muted }]}>{g.title}</Text>
          <View style={[styles.list, { backgroundColor: t.card, borderColor: t.line }]}>
            {g.items.map((it, i) => (
              <Pressable
                key={it.title}
                accessibilityRole="button"
                onPress={() => router.push(it.href)}
                style={({ pressed }) => [styles.item, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.line }, pressed && { backgroundColor: t.soft }]}>
                <View style={[styles.icon, { backgroundColor: t.soft }]}><Ionicons name={it.icon} size={18} color={t.text} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.text, fontSize: 15.5, fontWeight: '500' }}>{it.title}</Text>
                  <Text style={{ color: t.muted, fontSize: 13 }}>{it.sub}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={t.muted} />
              </Pressable>
            ))}
          </View>
        </View>
      ))}

      <Pressable accessibilityRole="button" onPress={signOut} style={({ pressed }) => [styles.signout, { opacity: pressed ? 0.6 : 1 }]}>
        <Text style={{ color: t.rose, fontSize: 15, fontWeight: '500' }}>{me?.demo ? 'End the demo' : 'Sign out'}</Text>
      </Pressable>
    </Screen>
  );
}

const styles = StyleSheet.create({
  profile: { flexDirection: 'row', alignItems: 'center', gap: space.m, borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.l, padding: space.l },
  avatar: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  group: { fontSize: 12, fontWeight: '600', letterSpacing: 0.9, textTransform: 'uppercase', marginTop: 28, marginBottom: 10 },
  list: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.l, overflow: 'hidden' },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.m, paddingHorizontal: space.l, paddingVertical: 13 },
  icon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  signout: { alignItems: 'center', paddingVertical: space.l, marginTop: space.l },
});
