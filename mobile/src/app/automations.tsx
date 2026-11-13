import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, Share, View } from 'react-native';

import { Button, Card, Chip, Empty, ErrorText, Field, P, Pill, Rich, Row, Screen, Section, Text, when } from '@/components/ui';
import { api, type Automation } from '@/lib/api';
import { radius, space, useTheme } from '@/lib/theme';

const EXAMPLES: { title: string; source: 'email' | 'webhook'; from?: string; subject?: string; instruction: string }[] = [
  { title: 'Supplier invoices', source: 'email', subject: 'invoice', instruction: 'Note the amount and due date, and remind me two days before it is due.' },
  { title: 'New order enquiries', source: 'email', subject: 'quote', instruction: 'Draft a reply with our price list and ask for the delivery address. Leave it for my approval.' },
  { title: 'Failed payments', source: 'webhook', instruction: 'Tell me which customer’s payment failed and draft a polite reminder for them.' },
];

export default function Automations() {
  const t = useTheme();
  const [rows, setRows] = useState<Automation[] | null>(null);
  const [source, setSource] = useState<'email' | 'webhook'>('email');
  const [title, setTitle] = useState('');
  const [from, setFrom] = useState('');
  const [subject, setSubject] = useState('');
  const [text, setText] = useState('');
  const [instruction, setInstruction] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setRows(await api<Automation[]>('/triggers')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const applyExample = (e: typeof EXAMPLES[number]) => {
    setSource(e.source); setTitle(e.title); setFrom(e.from || ''); setSubject(e.subject || ''); setText(''); setInstruction(e.instruction);
  };

  const add = async () => {
    setError('');
    try {
      await api('/triggers', { method: 'POST', body: { title: title.trim(), source, instruction: instruction.trim(),
        match: source === 'email' ? { from: from.trim(), subject: subject.trim(), text: text.trim() } : {} } });
      setTitle(''); setFrom(''); setSubject(''); setText(''); setInstruction('');
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  const set = async (a: Automation, op: 'pause' | 'resume') => { await api(`/triggers/${a.id}/${op}`, { method: 'POST' }); await load(); };
  const remove = async (a: Automation) => { await api(`/triggers/${a.id}`, { method: 'DELETE' }); await load(); };

  const filterMissing = source === 'email' && !from.trim() && !subject.trim() && !text.trim();

  return (
    <Screen edges={[]}>
      <P muted>When something happens, your assistant acts. It reads the email or event as information only, and anything it wants to send still waits for your yes.</P>

      <Section>New automation</Section>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.s, marginBottom: space.m }}>
        {EXAMPLES.map(e => <Chip key={e.title} label={e.title} onPress={() => applyExample(e)} />)}
      </View>
      <View style={{ flexDirection: 'row', backgroundColor: t.soft, borderRadius: radius.pill, padding: 4, marginBottom: space.m }} accessibilityRole="tablist">
        {(['email', 'webhook'] as const).map(k => (
          <Pressable key={k} accessibilityRole="tab" accessibilityState={{ selected: source === k }} onPress={() => setSource(k)}
            style={{ flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: radius.pill, backgroundColor: source === k ? t.card : 'transparent' }}>
            <Text style={{ color: source === k ? t.text : t.muted, fontWeight: '600', fontSize: 14 }}>{k === 'email' ? 'When an email arrives' : 'When a webhook fires'}</Text>
          </Pressable>
        ))}
      </View>
      <Field label="Name" value={title} onChangeText={setTitle} placeholder="Supplier invoices" />
      {source === 'email' ? (
        <>
          <Field label="From contains" value={from} onChangeText={setFrom} autoCapitalize="none" placeholder="billing@vendor.in" />
          <Field label="Subject contains" value={subject} onChangeText={setSubject} placeholder="invoice" />
          <Field label="Text contains (optional)" value={text} onChangeText={setText} placeholder="due date" />
        </>
      ) : (
        <P small muted style={{ marginBottom: space.m }}>You’ll get a secret link. Paste it into Stripe, Shopify, Zapier, a Google Form script or anything that can call a URL.</P>
      )}
      <Field label="What should your assistant do?" value={instruction} onChangeText={setInstruction} multiline placeholder="Note the amount and remind me before it’s due" />
      {filterMissing ? <P small muted style={{ marginBottom: space.s }}>Add at least one filter so it doesn’t run on every email.</P> : null}
      <ErrorText>{error}</ErrorText>
      <Button title="Create automation" onPress={add} disabled={title.trim().length < 2 || instruction.trim().length < 5 || filterMissing} />

      <Section>Your automations</Section>
      {rows && !rows.length ? <Empty>No automations yet. Pick an example above to start.</Empty> : null}
      {rows?.map(a => (
        <Card key={a.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <P bold style={{ flex: 1 }}>{a.title}</P>
            <Pill label={a.status === 'active' ? (a.source === 'email' ? 'Email' : 'Webhook') : 'Paused'} tone={a.status === 'active' ? 'neutral' : 'accent'} />
          </Row>
          <P small muted style={{ marginTop: 4 }}>{a.summary}</P>
          {a.webhook_url ? (
            <Pressable accessibilityRole="button" onPress={() => { void Share.share({ message: a.webhook_url! }); }}
              style={{ backgroundColor: t.soft, borderRadius: radius.m, padding: space.m, marginTop: space.m }}>
              <Text selectable style={{ color: t.text, fontSize: 12.5 }}>{a.webhook_url}</Text>
              <Text style={{ color: t.ink2, fontSize: 12.5, fontWeight: '600', marginTop: 4 }}>Share link</Text>
            </Pressable>
          ) : null}
          <P small muted style={{ marginTop: space.s }}>{a.fires ? `Ran ${a.fires} time${a.fires === 1 ? '' : 's'}${a.last_fired_at ? `, last ${when(a.last_fired_at)}` : ''}` : 'Hasn’t run yet'}</P>
          {a.last_result ? <Rich text={a.last_result} style={{ fontSize: 14, marginTop: 6 }} /> : null}
          <Row style={{ marginTop: space.m }}>
            <Button small kind="ghost" title={a.status === 'active' ? 'Pause' : 'Resume'} onPress={() => set(a, a.status === 'active' ? 'pause' : 'resume')} style={{ flex: 1 }} />
            <Button small kind="warn" title="Delete" onPress={() => remove(a)} style={{ flex: 1 }} />
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
