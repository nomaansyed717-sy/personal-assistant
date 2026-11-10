import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

import { Button, Card, Empty, ErrorText, Field, P, Row, Screen, Section } from '@/components/ui';
import { api, type Memory } from '@/lib/api';

export default function MemoryScreen() {
  const [items, setItems] = useState<Memory[] | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setItems(await api<Memory[]>('/memories')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  return (
    <Screen edges={[]}>
      <P muted>What your assistant knows about you. Delete anything, any time.</P>
      <Section>Tell it something to remember</Section>
      <Field value={text} onChangeText={setText} placeholder="I never take meetings before 10am" />
      <ErrorText>{error}</ErrorText>
      <Button title="Remember" disabled={text.trim().length < 3} onPress={async () => {
        setError('');
        try { await api('/memories', { method: 'POST', body: { text: text.trim() } }); setText(''); await load(); }
        catch (e) { setError((e as Error).message); }
      }} />
      <Section>Saved</Section>
      {items && !items.length ? <Empty>Nothing saved yet. Your assistant learns as you chat.</Empty> : null}
      {items?.map(m => (
        <Card key={m.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <P style={{ flex: 1 }}>{m.text}</P>
            <Button small kind="ghost" title="Forget" onPress={async () => { await api(`/memories/${m.id}`, { method: 'DELETE' }); await load(); }} />
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
