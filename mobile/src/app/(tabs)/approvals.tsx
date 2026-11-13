import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, StyleSheet, View } from 'react-native';

import { Button, Empty, ErrorText, Pill, Rich, Row, Screen, Text, Title, when } from '@/components/ui';
import { api, type Approval } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useBadge } from '@/lib/badge';
import { startQueued } from '@/lib/phone';
import { radius, space, useTheme } from '@/lib/theme';

const KIND: Record<string, string> = {
  send_email: 'Email, ready to send', reply_email: 'Reply, ready to send', create_event: 'Calendar hold',
  purchase: 'Purchase, you do the checkout', browser_task: 'Web task on the secure browser', phone_call: 'Phone call',
  phone_task: 'Task on your phone, up to payment',
  send_message: 'Message, ready to send', note: 'Reminder to close the loop',
};
const FIELDS: [string, string][] = [
  ['to', 'To'], ['cc', 'Cc'], ['subject', 'Subject'], ['body', 'Message'], ['title', 'Title'], ['start', 'Starts'], ['end', 'Ends'],
  ['attendees', 'Guests'], ['item', 'Item'], ['price', 'Price'], ['merchant', 'Store'], ['url', 'Link'], ['goal', 'Goal'], ['app', 'App'], ['start_url', 'Starts at'],
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
  const { token } = useAuth();
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
      if (a.kind === 'phone_task') {
        const job = await startQueued(token);
        if (job) setResults(x => ({ ...x, [a.id]: 'Started on your phone. Follow it in the Do it tab.' }));
      }
    } catch (e) { setResults(x => ({ ...x, [a.id]: (e as Error).message })); }
    void badge.refresh();
  };
  const skip = async (a: Approval) => {
    await api(`/approvals/${a.id}/reject`, { method: 'POST' });
    await load();
  };

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
      <Title sub="Nothing goes out, gets booked or gets paid until you say yes.">Approvals</Title>
      <ErrorText>{error}</ErrorText>
      {items && items.length === 0 ? (
        <Empty>Nothing waiting for you. When your assistant prepares an email, booking or purchase, it shows up here.</Empty>
      ) : null}
      {items?.map(a => {
        const rows = details(a.payload || {});
        const done = results[a.id];
        return (
          <View key={a.id} style={[styles.slip, { backgroundColor: t.card, borderColor: t.line }]}>
            <Row style={{ justifyContent: 'space-between', marginBottom: space.m }}>
              <Row>
                <View style={[styles.num, { backgroundColor: t.marigoldSoft }]}>
                  <Text style={{ color: t.ink2, fontWeight: '700', fontSize: 13 }}>{a.number}</Text>
                </View>
                <Text style={[styles.kind, { color: t.muted }]}>{KIND[a.kind] || 'Ready when you are'}</Text>
              </Row>
              {a.tier >= 3 ? <Pill label={a.kind === 'purchase' ? 'Spends money' : 'Check carefully'} tone="accent" /> : null}
            </Row>
            <Rich text={a.preview} />
            {rows.length ? (
              <Pressable onPress={() => setOpen(o => ({ ...o, [a.id]: !o[a.id] }))} accessibilityRole="button" style={{ marginTop: space.m }}>
                <Text style={{ color: t.muted, fontWeight: '500', fontSize: 13.5 }}>{open[a.id] ? 'Hide details' : 'See exactly what will happen  ›'}</Text>
              </Pressable>
            ) : null}
            {open[a.id] ? (
              <View style={[styles.dl, { backgroundColor: t.soft }]}>
                {rows.map(([k, v]) => (
                  <View key={k} style={{ gap: 2 }}>
                    <Text style={{ color: t.muted, fontSize: 12 }}>{k}</Text>
                    <Text style={{ color: t.text, fontSize: 14.5 }}>{v}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            <View style={{ marginTop: space.l }}>
              {done ? (
                <Row style={{ alignItems: 'flex-start' }}>
                  <Text style={{ color: t.leaf, fontWeight: '700' }}>✓</Text>
                  <Rich text={done} style={{ fontSize: 14, flex: 1 }} color={t.muted} />
                </Row>
              ) : (
                <Row>
                  <Button small title={a.kind === 'note' ? 'Mark handled' : 'Approve'} onPress={() => approve(a)} style={{ flex: 1 }} />
                  <Button small kind="ghost" title="Skip" onPress={() => skip(a)} style={{ flex: 1 }} />
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
  slip: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.l, padding: 18, marginBottom: space.m },
  num: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  kind: { fontSize: 13, fontWeight: '500' },
  dl: { borderRadius: radius.m, padding: 14, marginTop: space.m, gap: space.m },
});
