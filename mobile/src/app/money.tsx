import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

import { Button, Card, Empty, ErrorText, P, Row, Screen, Section, money } from '@/components/ui';
import { api, type Subscription } from '@/lib/api';

const PER_MONTH: Record<string, number> = { monthly: 1, yearly: 1 / 12, weekly: 52 / 12 };
const PER: Record<string, string> = { monthly: ' / month', yearly: ' / year', weekly: ' / week' };

export default function Money() {
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  const [error, setError] = useState('');

  useFocusEffect(useCallback(() => {
    api<Subscription[]>('/subscriptions').then(setSubs).catch(e => setError(e.message));
  }, []));

  const cur = subs?.[0]?.currency || 'INR';
  const same = subs?.every(s => (s.currency || 'INR') === cur);
  const total = (subs || []).reduce((t, s) => t + (s.status !== 'cancelled' && s.amount ? s.amount * (PER_MONTH[s.cadence || ''] ?? 0) : 0), 0);

  return (
    <Screen edges={[]}>
      <P muted>Recurring charges your assistant found in your email. It flags the ones you don't use and lines up cancellations for your yes.</P>
      <ErrorText>{error}</ErrorText>
      {subs && same && total ? (
        <Card accent><P bold>About {money(total, cur)} a month across {subs.length} subscriptions.</P></Card>
      ) : null}
      <Row style={{ marginVertical: 8, flexWrap: 'wrap' }}>
        <Button small title="Audit my subscriptions" onPress={() => router.push({ pathname: '/chat', params: { draft: 'Audit my subscriptions and tell me which to keep or cancel' } })} />
        <Button small kind="ghost" title="Watch a price" onPress={() => router.push({ pathname: '/chat', params: { draft: 'Watch the price of ' } })} />
      </Row>
      <Section>Subscriptions</Section>
      {subs && !subs.length ? <Empty>No recurring charges found yet. They appear as your email is read.</Empty> : null}
      {subs?.map(s => (
        <Card key={s.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <P style={{ flex: 1 }}>{s.merchant}{s.status === 'cancelled' ? ' (cancelled)' : ''}</P>
            <P bold>{s.amount != null ? money(s.amount, s.currency || cur) + (PER[s.cadence || ''] || '') : 'Amount unknown'}</P>
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
