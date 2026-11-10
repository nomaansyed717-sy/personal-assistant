import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

import { Button, Card, ErrorText, Field, P, Row, Screen, Section } from '@/components/ui';
import { api, type Skill } from '@/lib/api';

export default function Skills() {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [steps, setSteps] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setSkills(await api<Skill[]>('/skills')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  return (
    <Screen edges={[]}>
      <P muted>Routines your assistant can run. Teach it new ones in chat ("save this as a skill") or here.</P>
      <Section>Skills</Section>
      {skills?.map(s => (
        <Card key={s.name}>
          <P bold>{s.name}</P>
          <P small muted>{s.description + (s.builtin ? '' : ' · yours')}</P>
          <Row style={{ marginTop: 8 }}>
            <Button small title="Run" onPress={() => router.push({ pathname: '/chat', params: { draft: `use the ${s.name} skill` } })} />
            {!s.builtin && s.id ? (
              <Button small kind="ghost" title="Delete" onPress={async () => { await api(`/skills/${s.id}`, { method: 'DELETE' }); await load(); }} />
            ) : null}
          </Row>
        </Card>
      ))}
      <Section>Teach a new skill</Section>
      <Field label="Name" value={name} onChangeText={setName} placeholder="vendor-reorder" autoCapitalize="none" />
      <Field label="What it's for" value={desc} onChangeText={setDesc} placeholder="Reorder stock from my usual vendors" />
      <Field label="Steps" value={steps} onChangeText={setSteps} multiline placeholder="1. Search email for low-stock alerts…" />
      <ErrorText>{error}</ErrorText>
      <Button title="Save skill" disabled={name.trim().length < 2 || desc.trim().length < 3 || steps.trim().length < 10} onPress={async () => {
        setError('');
        try {
          await api('/skills', { method: 'POST', body: { name: name.trim(), description: desc.trim(), instructions: steps.trim() } });
          setName(''); setDesc(''); setSteps('');
          await load();
        } catch (e) { setError((e as Error).message); }
      }} />
    </Screen>
  );
}
