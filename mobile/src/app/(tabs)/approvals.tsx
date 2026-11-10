import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { Button, Empty, ErrorText, Rich, Row, Screen, Title, when } from '@/components/ui';
import { api, type Approval } from '@/lib/api';
import { useBadge } from '@/lib/badge';
import { radius, space, useTheme } from '@/lib/theme';

const KIND: Record<string, string> = {
  send_email: 'Email, ready to send', reply_email: 'Reply, ready to send', create_event: 'Calendar hold',
  purchase: 'Purchase, you do the checkout', browser_task: 'Web task on the secure browser', phone_call: 'Phone call',
  send_message: 'Message, ready to send', note: 'Reminder to close the loop',
};
const FIELDS: [string, string][] = [
  ['to', 'To'], ['cc', 'Cc'], ['subject', 'Subject'], ['body', 'Message'], ['title', 'Title'], ['start', 'Starts'], ['end', 'Ends'],
  ['attendees', 'Guests'], ['item', 'Item'], ['price', 'Price'], ['merchant', 'Store'], ['url', 'Link'], ['goal', 'Goal'], ['start_url', 'Starts at'],
];

function details(p: Record<string, unknown>): [string, string][] {
  return FIELDS.filter(([k]) => p[k] != null && p[k] !== '' && !(Array.isArray(p[k]) && !(p[k] as unknown[]).length)).map(([k, label]) => {
    const v = p[k];
    const s = Array.isArray(v) ? v.join(', ') : String(v);
    return [label, /^\d{4}-\d\d-\d\dT/.test(s) ? when(s) : s];
  });
}

export default function Approvals() {
  const t = useTheme();
  const badge = useBadge();
  const [items, setItems] = useState<Approval[] | null>(null);
  const [results, setResults] = useState<Record<number, string>>({});
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setItems(await api<Approval[]>('/approvals')); setError(''); }
    catch (e) { setError((e as Error).message); }
    void badge.refresh();
  }, [badge]);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const approve = async (a: Approval) => {
    try {
      const r = await api<{ result: string }>(`/approvals/${a.id}/approve`, { method: 'POST' });
      setResults(x => ({ ...x, [a.id]: r.result }));
    } catch (e) { setResults(x => ({ ...x, [a.id]: (e as Error).message })); }
    void badge.refresh();
  };
  const skip = async (a: Approval) => {
    await api(`/approvals/${a.id}/reject`, { method: 'POST' });
    await load();
  };

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
      <Title sub="Nothing sensitive happens until you approve it.">Approvals</Title>
      <ErrorText>{error}</ErrorText>
      {items && items.length === 0 ? (
        <Empty>Nothing waiting for you. When your assistant prepares an email, booking or purchase, it shows up here.</Empty>
      ) : null}
      {items?.map(a => {
        const rows = details(a.payload || {});
        const done = results[a.id];
        return (
          <View key={a.id} style={[styles.slip, { backgroundColor: t.card, borderColor: t.line }]}>
            <View style={[styles.stub, { backgroundColor: t.marigoldSoft, borderRightColor: t.marigold }]}>
              <Text style={[styles.num, { color: t.text }]}>{a.number}</Text>
            </View>
            <View style={styles.main}>
              <Text style={[styles.kind, { color: t.muted }]}>{KIND[a.kind] || 'Ready when you are'}</Text>
              {a.tier >= 3 ? (
                <Text style={[styles.kind, { color: t.rose }]}>
                  {a.kind === 'purchase' ? 'Spends money: check the price and store' : 'New contact or real-world action: check carefully'}
                </Text>
              ) : null}
              <Rich text={a.preview} style={{ marginVertical: space.s }} />
              {rows.length ? (
                <Pressable onPress={() => setOpen(o => ({ ...o, [a.id]: !o[a.id] }))} accessibilityRole="button">
                  <Text style={{ color: t.ink2, fontWeight: '600', marginBottom: space.s }}>{open[a.id] ? 'Hide details' : 'See exactly what will happen'}</Text>
                </Pressable>
              ) : null}
              {open[a.id] ? (
                <View style={[styles.dl, { backgroundColor: t.bg }]}>
                  {rows.map(([k, v]) => (
                    <View key={k} style={{ marginBottom: 6 }}>
                      <Text style={{ color: t.muted, fontSize: 12 }}>{k}</Text>
                      <Text style={{ color: t.text }}>{v}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
              {done ? (
                <Rich text={done} style={{ fontSize: 14 }} color={t.leaf} />
              ) : (
                <Row>
                  <Button small title="Approve" onPress={() => approve(a)} />
                  <Button small kind="ghost" title="Skip" onPress={() => skip(a)} />
                </Row>
              )}
            </View>
          </View>
        );
      })}
    </Screen>
  );
}

const styles = StyleSheet.create({
  slip: { flexDirection: 'row', borderWidth: 1, borderRadius: radius.s, overflow: 'hidden', marginBottom: space.m },
  stub: { width: 64, alignItems: 'center', justifyContent: 'center', borderRightWidth: 2, borderStyle: 'dashed' },
  num: { fontSize: 30, fontWeight: '700' },
  main: { flex: 1, padding: space.l },
  kind: { fontSize: 13, fontWeight: '600' },
  dl: { borderRadius: radius.s, padding: space.m, marginBottom: space.m },
});
