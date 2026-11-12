import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, StyleSheet, View } from 'react-native';

import { Button, Card, Empty, ErrorText, P, Row, Screen, Section, Text, money } from '@/components/ui';
import { api, type Today } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

export default function TodayScreen() {
  const t = useTheme();
  const { me } = useAuth();
  const [data, setData] = useState<Today | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api<Today>('/today')); setError(''); }
    catch (e) { setError((e as Error).message); }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const loop = async (id: number, action: 'done' | 'snooze') => {
    await api(`/loops/${id}`, { method: 'POST', body: action === 'done' ? { action } : { action, days: 3 } });
    await load();
  };

  const date = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  const cur = data ? Object.keys(data.subscriptions_monthly)[0] : undefined;

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={t.muted} />}>
      <View style={styles.head}>
        <Text style={{ color: t.muted, fontSize: 13.5, fontWeight: '500' }}>
          {date}{data?.paused ? ' · paused' : ''}{me?.demo ? ' · demo' : ''}
        </Text>
        <Text style={[styles.greeting, { color: t.text }]}>{data?.greeting || 'Today'}</Text>
      </View>
      <ErrorText>{error}</ErrorText>

      {data && (
        <>
          {data.approvals > 0 ? (
            <Pressable accessibilityRole="button" onPress={() => router.push('/approvals')}
              style={({ pressed }) => [styles.callout, { backgroundColor: t.marigoldSoft, opacity: pressed ? 0.8 : 1 }]}>
              <View style={[styles.count, { backgroundColor: t.marigold }]}>
                <Text style={{ color: t.onAccent, fontWeight: '700', fontSize: 15 }}>{data.approvals}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: t.text, fontWeight: '600', fontSize: 15 }}>{data.approvals === 1 ? 'One thing needs your yes' : `${data.approvals} things need your yes`}</Text>
                <Text style={{ color: t.muted, fontSize: 13 }}>Drafts and bookings, ready to go</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={t.ink2} />
            </Pressable>
          ) : null}

          <View style={styles.stats}>
            <Stat value={String(data.loops.length)} label="Open loops" />
            <Stat value={String(data.standing_tasks)} label="Running tasks" onPress={() => router.push('/tasks')} />
            {cur ? <Stat value={money(data.subscriptions_monthly[cur], cur)} label="Subscriptions / mo" onPress={() => router.push('/money')} /> : null}
          </View>

          <Section>Needs you</Section>
          {data.loops.length === 0 ? (
            <Empty>Nothing slipping. Tell your assistant about a promise, or connect Google so it finds them for you.</Empty>
          ) : data.loops.map(l => (
            <Card key={l.id}>
              <Row style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                <Text style={{ color: l.direction === 'user_owes' ? t.ink2 : t.muted, fontSize: 12.5, fontWeight: '600' }}>
                  {(l.direction === 'user_owes' ? 'You owe ' : 'Waiting on ') + (l.person || 'someone')}
                </Text>
                {l.due_at ? <Text style={{ color: t.muted, fontSize: 12.5 }}>Due {new Date(l.due_at).toLocaleDateString([], { day: 'numeric', month: 'short' })}</Text> : null}
              </Row>
              <P>{l.description}</P>
              <Row style={{ marginTop: space.m, flexWrap: 'wrap' }}>
                <Button small title="Draft it" onPress={() => router.push({ pathname: '/chat', params: { draft: `Draft what I need to send for: ${l.description}` } })} />
                <Button small kind="ghost" title="Done" onPress={() => loop(l.id, 'done')} />
                <Button small kind="plain" title="Snooze" onPress={() => loop(l.id, 'snooze')} />
              </Row>
            </Card>
          ))}

          <Section>Today</Section>
          {data.events.length === 0 ? <Empty>Your calendar is clear.</Empty> : (
            <Card style={{ paddingVertical: 6 }}>
              {data.events.map((e, i) => (
                <View key={i} style={[styles.event, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.line }]}>
                  <Text style={{ color: t.muted, fontSize: 13.5, width: 58, fontVariant: ['tabular-nums'] }}>
                    {new Date(e.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                  <P style={{ flex: 1 }}>{e.title}</P>
                </View>
              ))}
            </Card>
          )}

          <Section action={<Button small kind="plain" title="Manage" onPress={() => router.push('/goals')} />}>Goals</Section>
          {data.goals.length === 0 ? (
            <Empty>Add a goal and your assistant suggests next steps each evening.</Empty>
          ) : data.goals.map(g => (
            <Card key={g.id} flat>
              <P bold>{g.title}</P>
              {g.progress_note ? <P small muted style={{ marginTop: 2 }}>{g.progress_note}</P> : null}
            </Card>
          ))}
        </>
      )}
    </Screen>
  );
}

function Stat({ value, label, onPress }: { value: string; label: string; onPress?: () => void }) {
  const t = useTheme();
  return (
    <Pressable accessibilityRole={onPress ? 'button' : undefined} onPress={onPress} disabled={!onPress}
      style={({ pressed }) => [styles.stat, { backgroundColor: t.card, borderColor: t.line, opacity: pressed ? 0.7 : 1 }]}>
      <Text style={[styles.statValue, { color: t.text }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <Text style={{ color: t.muted, fontSize: 12.5 }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  head: { marginTop: space.s, marginBottom: space.xl, gap: 4 },
  greeting: { fontSize: 32, lineHeight: 38, fontWeight: '700', letterSpacing: -1 },
  callout: { flexDirection: 'row', alignItems: 'center', gap: space.m, borderRadius: radius.l, padding: space.l, marginBottom: space.m },
  count: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  stats: { flexDirection: 'row', gap: space.s, flexWrap: 'wrap' },
  stat: { flexGrow: 1, flexBasis: 100, borderRadius: radius.m, padding: 14, borderWidth: StyleSheet.hairlineWidth, gap: 2 },
  statValue: { fontSize: 22, fontWeight: '700', letterSpacing: -0.6, fontVariant: ['tabular-nums'] },
  event: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
});
