import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Button, Card, Empty, ErrorText, Field, P, Rich, Screen, Section, when } from '@/components/ui';
import { api, type StandingTask } from '@/lib/api';
import { radius, space, useTheme } from '@/lib/theme';

const SCHEDULES = [
  { v: 'every 12h', label: 'Every 12 hours' },
  { v: 'daily 09:00', label: 'Every day at 9:00' },
  { v: 'weekly fri 16:00', label: 'Fridays at 16:00' },
  { v: 'every 1h', label: 'Every hour' },
];
const DAYS: Record<string, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' };
const UNITS: Record<string, string> = { m: 'minutes', h: 'hours', d: 'days' };

function schedText(s: string) {
  let m: RegExpExecArray | null;
  if ((m = /^daily (\d\d:\d\d)$/.exec(s))) return 'Every day at ' + m[1];
  if ((m = /^weekly (\w{3}) (\d\d:\d\d)$/.exec(s))) return `Every ${DAYS[m[1]] || m[1]} at ${m[2]}`;
  if ((m = /^every (\d+)([mhd])$/.exec(s))) return `Every ${m[1]} ${UNITS[m[2]]}`;
  if ((m = /^once (.+)$/.exec(s))) return 'Once, ' + when(m[1]);
  return s;
}

export default function Tasks() {
  const t = useTheme();
  const [tasks, setTasks] = useState<StandingTask[] | null>(null);
  const [title, setTitle] = useState('');
  const [instr, setInstr] = useState('');
  const [sched, setSched] = useState(SCHEDULES[0].v);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setTasks(await api<StandingTask[]>('/tasks')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const add = async () => {
    setError('');
    try {
      await api('/tasks', { method: 'POST', body: { title: title.trim(), instruction: instr.trim(), schedule: sched } });
      setTitle(''); setInstr('');
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <Screen edges={[]}>
      <P muted>Work that keeps running after you close the app. It messages you only when something changed.</P>
      <Section>New standing task</Section>
      <Field label="Name" value={title} onChangeText={setTitle} placeholder="Watch the price of the Kindle Paperwhite" />
      <Field label="What to do each time" value={instr} onChangeText={setInstr} multiline placeholder="Read https://… and tell me if the price is under ₹12,000" />
      <Text style={{ color: t.text, fontWeight: '600', fontSize: 14, marginBottom: 6 }}>How often</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.s, marginBottom: space.m }}>
        {SCHEDULES.map(s => (
          <Pressable key={s.v} accessibilityRole="radio" accessibilityState={{ selected: sched === s.v }} onPress={() => setSched(s.v)}
            style={{ borderWidth: 1, borderColor: sched === s.v ? t.ink : t.line, backgroundColor: sched === s.v ? t.ink : t.card, borderRadius: radius.pill, paddingVertical: 7, paddingHorizontal: 12 }}>
            <Text style={{ color: sched === s.v ? '#fff' : t.text }}>{s.label}</Text>
          </Pressable>
        ))}
      </View>
      <ErrorText>{error}</ErrorText>
      <Button title="Start task" onPress={add} disabled={title.trim().length < 2 || instr.trim().length < 5} />
      <Section>Running and finished</Section>
      {tasks && !tasks.length ? <Empty>No standing tasks yet. Try "watch this price" or "check every morning if a slot opened".</Empty> : null}
      {tasks?.map(task => (
        <Card key={task.id}>
          <P bold>{task.title}</P>
          <P small muted>{[schedText(task.schedule), task.status !== 'active' && task.status, task.status === 'active' && task.next_run_at && `next ${when(task.next_run_at)}`,
            task.runs ? `ran ${task.runs} time${task.runs === 1 ? '' : 's'}` : 'not run yet'].filter(Boolean).join(' · ')}</P>
          {task.last_result ? <Rich text={'Last: ' + task.last_result} style={{ fontSize: 14, marginTop: 6 }} /> : null}
          {task.status === 'active' ? (
            <Button small kind="ghost" title="Stop" style={{ alignSelf: 'flex-start', marginTop: 8 }}
              onPress={async () => { await api(`/tasks/${task.id}`, { method: 'DELETE' }); await load(); }} />
          ) : null}
        </Card>
      ))}
    </Screen>
  );
}
