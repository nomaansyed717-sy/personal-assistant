import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Empty, ErrorText, P, Screen, when } from '@/components/ui';
import { api, type Activity } from '@/lib/api';
import { radius, space, useTheme } from '@/lib/theme';

export default function ActivityScreen() {
  const t = useTheme();
  const [data, setData] = useState<Activity | null>(null);
  const [tab, setTab] = useState<'planned' | 'done'>('planned');
  const [error, setError] = useState('');

  useFocusEffect(useCallback(() => {
    api<Activity>('/activity').then(setData).catch(e => setError(e.message));
  }, []));

  return (
    <Screen edges={[]}>
      <P muted style={{ marginBottom: space.m }}>Everything your assistant has done this week, and what it's about to do.</P>
      <View style={[styles.tabs, { backgroundColor: t.card, borderColor: t.line }]} accessibilityRole="tablist">
        {(['planned', 'done'] as const).map(k => (
          <Pressable key={k} accessibilityRole="tab" accessibilityState={{ selected: tab === k }} onPress={() => setTab(k)}
            style={[styles.tab, tab === k && { backgroundColor: t.ink }]}>
            <Text style={{ color: tab === k ? '#fff' : t.text, fontWeight: '600' }}>{k === 'planned' ? 'Planned' : 'Done'}</Text>
          </Pressable>
        ))}
      </View>
      <ErrorText>{error}</ErrorText>
      {data && tab === 'planned' && (data.planned.length ? data.planned.map((p, i) => (
        <Item key={i} title={p.what} sub={/^\d{4}-/.test(p.when) ? when(p.when) : p.when} />
      )) : <Empty>Nothing planned. Ask your assistant to keep an eye on something.</Empty>)}
      {data && tab === 'done' && (data.done.length ? data.done.map((d, i) => (
        <Item key={i} title={d.label} body={d.detail} sub={when(d.at) + (d.actor === 'user' ? ', by you' : '')}
          color={d.action === 'blocked' ? t.rose : d.action === 'executed' ? t.leaf : t.line} />
      )) : <Empty>No activity yet this week.</Empty>)}
    </Screen>
  );
}

function Item({ title, body, sub, color }: { title: string; body?: string; sub?: string; color?: string }) {
  const t = useTheme();
  return (
    <View style={styles.item}>
      <View style={[styles.dot, { backgroundColor: color || t.line }]} />
      <View style={{ flex: 1, paddingBottom: space.m, borderLeftWidth: 2, borderLeftColor: t.line, paddingLeft: space.l, marginLeft: -6 }}>
        <P bold>{title}</P>
        {body ? <P>{body}</P> : null}
        {sub ? <P small muted>{sub}</P> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  tabs: { flexDirection: 'row', borderWidth: 1, borderRadius: radius.pill, padding: 3, marginBottom: space.l, alignSelf: 'flex-start' },
  tab: { paddingVertical: 7, paddingHorizontal: 18, borderRadius: radius.pill },
  item: { flexDirection: 'row' },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 6, zIndex: 1 },
});
