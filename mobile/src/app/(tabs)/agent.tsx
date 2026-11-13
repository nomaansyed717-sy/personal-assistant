import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { AppState, Platform, RefreshControl, StyleSheet, View } from 'react-native';

import { Button, Card, Chip, Empty, ErrorText, P, Pill, Row, Screen, Section, Text, TextInput, Title, when } from '@/components/ui';
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

  const recent = jobs.filter(j => j !== active);

  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={t.muted} />}>
      <Title eyebrow="Phone agent" sub="Tell me what to do. I'll use the apps on your phone, and stop for you to sign in and to pay.">Do it for me</Title>

      <View style={[styles.composer, { backgroundColor: t.card, borderColor: t.line }]}>
        <TextInput
          value={goal}
          onChangeText={setGoal}
          placeholder="Book the cheapest AC sleeper from Pune to Aurangabad on Friday night"
          placeholderTextColor={t.muted}
          multiline
          style={[styles.input, { color: t.text }]}
          accessibilityLabel="Task for the phone agent"
        />
        <Row style={{ justifyContent: 'space-between' }}>
          <Row style={{ gap: 6 }}>
            <Ionicons name="lock-closed" size={13} color={t.muted} />
            <Text style={{ color: t.muted, fontSize: 12.5 }}>You sign in and pay</Text>
          </Row>
          <Button small title="Do it" onPress={start} disabled={goal.trim().length < 3 || !!me?.demo} style={{ paddingHorizontal: 20 }} />
        </Row>
      </View>
      <ErrorText>{error}</ErrorText>
      <View style={styles.examples}>
        {EXAMPLES.slice(0, 4).map(e => <Chip key={e} label={e} onPress={() => setGoal(e)} />)}
      </View>

      {me?.demo ? (
        <Card flat style={{ marginTop: space.l }}><P small>The phone agent works in your own account on your Android phone. In the demo, ask in Chat and I’ll show what it would do.</P></Card>
      ) : !phoneAgentAvailable ? (
        <Card flat style={{ marginTop: space.l }}>
          {Platform.OS === 'android' ? (
            <>
              <P bold>This version doesn’t include the phone agent</P>
              <P small muted style={{ marginTop: 4 }}>It’s the version without the accessibility service, so it installs without being blocked. Install the full version to let Aide use your apps.</P>
            </>
          ) : (
            <>
              <P bold>Install the Android app to use this</P>
              <P small muted style={{ marginTop: 4 }}>The phone agent runs inside Aide’s Android app. It isn’t available in a browser or in Expo Go.</P>
            </>
          )}
        </Card>
      ) : !enabled ? (
        <Card style={{ marginTop: space.l }}>
          <Row style={{ gap: space.m, marginBottom: space.m }}>
            <View style={[styles.iconWrap, { backgroundColor: t.marigoldSoft }]}><Ionicons name="phone-portrait-outline" size={20} color={t.ink2} /></View>
            <View style={{ flex: 1 }}>
              <P bold>Let Aide use your apps</P>
              <P small muted>Uses Android’s accessibility service, only while a task you started is running.</P>
            </View>
          </Row>
          <View style={{ gap: 10, marginBottom: space.m }}>
            {[['hand-left-outline', 'Only runs when you give it a task, with a Stop button always on screen.'],
              ['key-outline', 'Never types passwords or OTPs. You sign in yourself.'],
              ['card-outline', "Never pays, and won't open UPI, wallet or banking apps."],
              ['eye-off-outline', 'Screen content decides each step and is never used for ads.']].map(([ic, x]) => (
              <Row key={x} style={{ alignItems: 'flex-start', gap: space.m }}>
                <Ionicons name={ic as keyof typeof Ionicons.glyphMap} size={17} color={t.muted} style={{ marginTop: 2 }} />
                <P small style={{ flex: 1 }}>{x}</P>
              </Row>
            ))}
          </View>
          <Button title="Turn on in Settings" onPress={() => { PhoneAgent.openSettings(); }} />
          <P small muted style={{ marginTop: space.s, textAlign: 'center' }}>Open “Aide phone agent” and switch it on.</P>
        </Card>
      ) : null}

      {active ? (
        <>
          <Section>Now</Section>
          <Card accent={active.status === 'waiting_user'}>
            <Row style={{ justifyContent: 'space-between', marginBottom: space.s }}>
              <Pill label={STATUS_LABEL[active.status]} tone={active.status === 'waiting_user' ? 'accent' : 'neutral'} />
              <Text style={{ color: t.muted, fontSize: 12.5 }}>{active.step_count} steps</Text>
            </Row>
            <P bold>{active.goal}</P>
            {active.message ? <P style={{ marginTop: 6 }}>{active.message}</P> : null}
            {active.status === 'waiting_user' && active.waiting_for ? <P small muted style={{ marginTop: 4 }}>{WAITING[active.waiting_for] || ''}</P> : null}
            <Row style={{ marginTop: space.l }}>
              {active.status === 'waiting_user' ? <Button small title="Resume" style={{ flex: 1 }} onPress={async () => { PhoneAgent.resume(); await load(); }} /> : null}
              {active.status === 'queued' && enabled ? <Button small title="Start now" style={{ flex: 1 }} onPress={async () => { await startQueued(token); await load(); }} /> : null}
              <Button small kind="warn" title="Stop" style={{ flex: 1 }} onPress={async () => {
                if (state.running || state.jobId === active.id) PhoneAgent.stop();
                await api(`/phone/jobs/${active.id}/event`, { method: 'POST', body: { type: 'stopped', detail: 'Stopped by you' } });
                await load();
              }} />
            </Row>
          </Card>
        </>
      ) : null}

      <Section>Recent</Section>
      {recent.length === 0 ? <Empty>Your tasks show up here, with what was done and what’s waiting for you.</Empty> : (
        <Card style={{ paddingVertical: 4 }}>
          {recent.map((j, i) => (
            <View key={j.id} style={[styles.row, i > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.line }]}>
              <Ionicons name={j.status === 'done' ? 'checkmark-circle' : j.status === 'waiting_user' ? 'hand-left' : 'remove-circle-outline'} size={20}
                color={j.status === 'done' ? t.leaf : j.status === 'waiting_user' ? t.marigold : t.muted} />
              <View style={{ flex: 1, gap: 2 }}>
                <P numberOfLines={2}>{j.goal}</P>
                <P small muted>{STATUS_LABEL[j.status]}{j.result ? ` · ${j.result}` : ''} · {when(j.updated_at)}</P>
              </View>
            </View>
          ))}
        </Card>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  composer: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.l, padding: 16, gap: space.m },
  input: { minHeight: 72, fontSize: 17, lineHeight: 24, textAlignVertical: 'top', padding: 0 },
  examples: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s, paddingTop: space.m },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', gap: space.m, alignItems: 'flex-start', paddingVertical: 12 },
});
