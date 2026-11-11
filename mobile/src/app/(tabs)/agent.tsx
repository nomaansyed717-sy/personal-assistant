import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { AppState, RefreshControl, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button, Card, Chip, Empty, ErrorText, P, Row, Screen, Section, Title, when } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { PhoneAgent, phoneAgentAvailable, startQueued, STATUS_LABEL, type PhoneJob } from '@/lib/phone';
import { radius, space, useTheme } from '@/lib/theme';

const EXAMPLES = [
  'Book a sleeper bus from Pune to Aurangabad this Friday night, under ₹1,500',
  'Book an auto to Aurangabad railway station now',
  'Find the cheapest flight from Mumbai to Dubai on 5 December, morning departure',
  'Book 2 tickets for the 7 pm show of the new Marathi film at the nearest PVR',
  'Check Tatkal 3A availability on the Devagiri Express to Mumbai tomorrow',
];

const WAITING: Record<string, string> = {
  login: 'Sign in to the app, then tap Resume.',
  otp: 'Enter the OTP in the app, then tap Resume.',
  captcha: 'Solve the captcha, then tap Resume.',
  payment: 'Check the details and pay in the app yourself. Tap Resume afterwards if you want me to confirm the booking.',
  question: 'Answer in the app or change the task, then tap Resume.',
  stuck: 'Take a look at the screen, then tap Resume or Stop.',
};

export default function Agent() {
  const t = useTheme();
  const { token, me } = useAuth();
  const [enabled, setEnabled] = useState(PhoneAgent.isEnabled());
  const [goal, setGoal] = useState('');
  const [jobs, setJobs] = useState<PhoneJob[]>([]);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [state, setState] = useState(PhoneAgent.getState());

  const load = useCallback(async () => {
    setEnabled(PhoneAgent.isEnabled());
    setState(PhoneAgent.getState());
    try { setJobs(await api<PhoneJob[]>('/phone/jobs?limit=15')); } catch (e) { setError((e as Error).message); }
  }, []);

  useFocusEffect(useCallback(() => {
    void load().then(() => startQueued(token)).then(j => { if (j) void load(); });
  }, [load, token]));

  // Live updates from the agent, and a re-check when the user comes back from Android's settings.
  useEffect(() => {
    const sub = PhoneAgent.addListener(() => { void load(); });
    const app = AppState.addEventListener('change', s => {
      if (s === 'active') void load().then(() => startQueued(token));
    });
    const id = setInterval(() => { if (PhoneAgent.getState().running) void load(); }, 5000);
    return () => { sub?.remove(); app.remove(); clearInterval(id); };
  }, [load, token]);

  const start = async () => {
    setError('');
    try {
      await api<PhoneJob>('/phone/jobs', { method: 'POST', body: { goal: goal.trim() } });
      setGoal('');
      const started = await startQueued(token);
      if (!started && phoneAgentAvailable && enabled) setError('Another task is running. It starts as soon as that one finishes.');
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  const active = jobs.find(j => j.status === 'running' || j.status === 'waiting_user' || j.status === 'queued');

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
      <Title sub="Tell me what to do. I'll use the apps on your phone, and stop for you to sign in and to pay.">Do it for me</Title>

      {me?.demo ? (
        <Card accent><P>The phone agent works in your own account on your Android phone. In the demo, ask in Chat and I'll show what it would do.</P></Card>
      ) : !phoneAgentAvailable ? (
        <Card accent>
          <P bold>Install the Android app to use this</P>
          <P small muted>The phone agent runs inside Aide's Android app (a development or release build). It isn't available in a browser or in Expo Go.</P>
        </Card>
      ) : !enabled ? (
        <Card accent>
          <P bold>Let Aide use your apps</P>
          <P small style={{ marginTop: 6 }}>
            To book tickets, cabs and more for you, Aide uses Android's accessibility service. While a task you started is running, it
            reads what's on your screen and taps and types in your apps.
          </P>
          <View style={{ gap: 4, marginVertical: space.s }}>
            {['It only runs when you give it a task, with a Stop button always on screen.',
              'It never types passwords or OTPs, and never pays: you sign in and pay yourself.',
              "It won't open payment apps like UPI apps, wallets or banking apps.",
              'Screen content is sent to Aide to decide each step, and never used for ads.'].map(x => (
              <Row key={x} style={{ alignItems: 'flex-start' }}><Text style={{ color: t.leaf, fontWeight: '700' }}>✓</Text><P small style={{ flex: 1 }}>{x}</P></Row>
            ))}
          </View>
          <P small muted>In the next screen, open "Aide phone agent" (under Installed apps or Downloaded apps) and switch it on.</P>
          <Button title="Turn on in Settings" onPress={() => { PhoneAgent.openSettings(); }} style={{ marginTop: space.m }} />
        </Card>
      ) : null}

      {active ? (
        <Card style={{ borderColor: active.status === 'waiting_user' ? t.marigold : t.line }} accent={active.status === 'waiting_user'}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Text style={[styles.badge, { color: active.status === 'waiting_user' ? t.rose : t.ink2 }]}>{STATUS_LABEL[active.status]}</Text>
            <P small muted>{active.step_count} steps</P>
          </Row>
          <P bold style={{ marginTop: 4 }}>{active.goal}</P>
          {active.message ? <P style={{ marginTop: 6 }}>{active.message}</P> : null}
          {active.status === 'waiting_user' && active.waiting_for ? <P small muted style={{ marginTop: 4 }}>{WAITING[active.waiting_for] || ''}</P> : null}
          <Row style={{ marginTop: space.m, flexWrap: 'wrap' }}>
            {active.status === 'waiting_user' ? <Button small title="Resume" onPress={async () => { PhoneAgent.resume(); await load(); }} /> : null}
            {active.status === 'queued' && enabled ? <Button small title="Start now" onPress={async () => { await startQueued(token); await load(); }} /> : null}
            <Button small kind="ghost" title="Stop" onPress={async () => {
              if (state.running || state.jobId === active.id) PhoneAgent.stop();
              await api(`/phone/jobs/${active.id}/event`, { method: 'POST', body: { type: 'stopped', detail: 'Stopped by you' } });
              await load();
            }} />
          </Row>
        </Card>
      ) : null}

      <Section>What should I do?</Section>
      <TextInput
        value={goal}
        onChangeText={setGoal}
        placeholder="e.g. Book the cheapest AC sleeper from Pune to Aurangabad on Friday night"
        placeholderTextColor={t.muted}
        multiline
        style={[styles.input, { color: t.text, backgroundColor: t.card, borderColor: t.line }]}
        accessibilityLabel="Task for the phone agent"
      />
      <ErrorText>{error}</ErrorText>
      <Button title="Do it" onPress={start} disabled={goal.trim().length < 3 || !!me?.demo} />
      <View style={styles.examples}>
        {EXAMPLES.map(e => <Chip key={e} label={e} onPress={() => setGoal(e)} />)}
      </View>

      <Section>Recent tasks</Section>
      {jobs.filter(j => j !== active).length === 0 ? <Empty>Your tasks show up here, with what was done and what's waiting for you.</Empty> : null}
      {jobs.filter(j => j !== active).map(j => (
        <View key={j.id} style={[styles.row, { backgroundColor: t.card, borderColor: t.line }]}>
          <Ionicons name={j.status === 'done' ? 'checkmark-circle' : j.status === 'waiting_user' ? 'hand-left' : 'close-circle'} size={20}
            color={j.status === 'done' ? t.leaf : j.status === 'waiting_user' ? t.marigold : t.muted} />
          <View style={{ flex: 1 }}>
            <P>{j.goal}</P>
            <P small muted>{STATUS_LABEL[j.status]}{j.result ? ` · ${j.result}` : ''} · {when(j.updated_at)}</P>
          </View>
        </View>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: { minHeight: 96, borderWidth: 1, borderRadius: radius.m, padding: space.m, fontSize: 16, textAlignVertical: 'top', marginBottom: space.s },
  examples: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s, marginTop: space.m },
  badge: { fontSize: 12, fontWeight: '700', letterSpacing: 0.4, textTransform: 'uppercase' },
  row: { flexDirection: 'row', gap: space.m, alignItems: 'flex-start', borderWidth: 1, borderRadius: radius.m, padding: space.m, marginBottom: space.s },
});
