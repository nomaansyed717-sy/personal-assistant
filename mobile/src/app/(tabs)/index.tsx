import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, ErrorText, P, Row, Screen, Section, Title, money } from '@/components/ui';
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

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const loop = async (id: number, action: 'done' | 'snooze') => {
    await api(`/loops/${id}`, { method: 'POST', body: action === 'done' ? { action } : { action, days: 3 } });
    await load();
  };

  const date = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  const cur = data ? Object.keys(data.subscriptions_monthly)[0] : undefined;

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={t.marigold} />}>
      <Title sub={date + (data?.paused ? ' · messages paused' : '') + (me?.demo ? ' · live demo' : '')}>
        {data?.greeting || 'Today'}
      </Title>
      <ErrorText>{error}</ErrorText>

      {data && (
        <>
          <View style={styles.stats}>
            <Stat big={String(data.approvals)} label={data.approvals === 1 ? 'waiting for your yes' : 'waiting for your yes'} accent={data.approvals > 0} onPress={() => router.push('/approvals')} />
            <Stat big={String(data.standing_tasks)} label="standing tasks" onPress={() => router.push('/tasks')} />
            {cur ? <Stat big={money(data.subscriptions_monthly[cur], cur)} label="a month in subscriptions" onPress={() => router.push('/money')} /> : null}
          </View>

          <Section>Needs you</Section>
          {data.loops.length === 0 ? (
            <Empty>Nothing slipping. Tell your assistant about a promise, or connect Google so it finds them for you.</Empty>
          ) : data.loops.map(l => (
            <Card key={l.id}>
              <Text style={[styles.who, { color: t.muted }]}>
                {(l.direction === 'user_owes' ? 'You owe ' : 'Waiting on ') + (l.person || 'someone')}
              </Text>
              <P style={{ marginVertical: 4 }}>{l.description}</P>
              {l.due_at ? <P small muted>Due {new Date(l.due_at).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}</P> : null}
              <Row style={{ marginTop: space.m, flexWrap: 'wrap' }}>
                <Button small title="Draft it" onPress={() => router.push({ pathname: '/chat', params: { draft: `Draft what I need to send for: ${l.description}` } })} />
                <Button small kind="ghost" title="Done" onPress={() => loop(l.id, 'done')} />
                <Button small kind="ghost" title="Snooze 3 days" onPress={() => loop(l.id, 'snooze')} />
              </Row>
            </Card>
          ))}

          <Section>On the calendar</Section>
          {data.events.length === 0 ? <Empty>Nothing on the calendar today.</Empty> : data.events.map((e, i) => (
            <Card key={i} style={styles.eventRow}>
              <Text style={[styles.time, { color: t.ink2 }]}>{new Date(e.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</Text>
              <P style={{ flex: 1 }}>{e.title}</P>
            </Card>
          ))}

          <Section>Goals</Section>
          {data.goals.length === 0 ? (
            <Empty>No goals yet. Add one and your assistant suggests next steps each evening.</Empty>
          ) : data.goals.map(g => (
            <Card key={g.id}>
              <P bold>{g.title}</P>
              {g.progress_note ? <P small muted>{g.progress_note}</P> : null}
            </Card>
          ))}
          <Button kind="ghost" small title="Manage goals" onPress={() => router.push('/goals')} style={{ alignSelf: 'flex-start', marginTop: space.xs }} />
        </>
      )}
    </Screen>
  );
}

function Stat({ big, label, onPress, accent }: { big: string; label: string; onPress: () => void; accent?: boolean }) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.stat, { backgroundColor: accent ? t.marigoldSoft : t.card, borderColor: accent ? t.marigold : t.line, opacity: pressed ? 0.8 : 1 }]}>
      <Text style={[styles.big, { color: t.text }]} numberOfLines={1} adjustsFontSizeToFit>{big}</Text>
      <Text style={{ color: t.muted, fontSize: 13 }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', gap: space.s, flexWrap: 'wrap' },
  stat: { flexGrow: 1, flexBasis: 140, borderWidth: 1, borderRadius: radius.m, padding: space.l },
  big: { fontSize: 28, fontWeight: '700' },
  who: { fontSize: 12, fontWeight: '700', letterSpacing: 0.4, textTransform: 'uppercase' },
  eventRow: { flexDirection: 'row', alignItems: 'center', gap: space.m },
  time: { fontWeight: '700', width: 64 },
});
