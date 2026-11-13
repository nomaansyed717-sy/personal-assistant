import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

import { Button, Card, Empty, ErrorText, Field, P, Row, Screen, Section } from '@/components/ui';
import { api, type Goal } from '@/lib/api';

export default function Goals() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setGoals(await api<Goal[]>('/goals')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const add = async () => {
    setError('');
    if (date && !/^\d{4}-\d\d-\d\d$/.test(date)) return setError('Use the date format YYYY-MM-DD, e.g. 2026-12-15.');
    try {
      await api('/goals', { method: 'POST', body: { title: title.trim(), target_date: date || null } });
      setTitle(''); setDate('');
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  const toggle = async (g: Goal) => {
    await api(`/goals/${g.id}`, { method: 'PATCH', body: { status: g.status === 'done' ? 'active' : 'done' } });
    await load();
  };

  return (
    <Screen edges={[]}>
      <P muted>Your assistant works toward these and suggests next steps each evening.</P>
      <Section>New goal</Section>
      <Field value={title} onChangeText={setTitle} placeholder="Open the Pune dark store by 15 December" />
      <Field label="Target date (optional)" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" keyboardType="numbers-and-punctuation" />
      <ErrorText>{error}</ErrorText>
      <Button title="Add goal" onPress={add} disabled={title.trim().length < 2} />
      <Section>Your goals</Section>
      {goals && !goals.length ? <Empty>Add a goal and your assistant will plan around it.</Empty> : null}
      {goals?.map(g => (
        <Card key={g.id}>
          <P bold style={g.status === 'done' ? { textDecorationLine: 'line-through' } : undefined}>{g.title}</P>
          <P small muted>{[g.status !== 'active' && g.status, g.target_date && `By ${new Date(g.target_date + 'T00:00').toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })}`, g.progress_note].filter(Boolean).join(' · ')}</P>
          <Row style={{ marginTop: 8 }}>
            <Button small kind="ghost" title={g.status === 'done' ? 'Reopen' : 'Mark done'} onPress={() => toggle(g)} />
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
