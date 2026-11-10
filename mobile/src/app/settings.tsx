import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Alert, Platform } from 'react-native';

import { Button, Card, ErrorText, Field, P, Row, Screen, Section, Toggle } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { space } from '@/lib/theme';

function confirm(title: string, body: string, yes: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(globalThis.confirm(`${title}\n\n${body}`));
  return new Promise(resolve =>
    Alert.alert(title, body, [
      { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
      { text: yes, style: 'destructive', onPress: () => resolve(true) },
    ]),
  );
}

export default function Settings() {
  const { me, refresh, signOut } = useAuth();
  const [name, setName] = useState(me?.assistant_name || '');
  const [persona, setPersona] = useState(me?.persona || '');
  const [tz, setTz] = useState(me?.timezone || '');
  const [hour, setHour] = useState(String(me?.brief_hour ?? 8));
  const [ideas, setIdeas] = useState(!!me?.ideas_enabled);
  const [paused, setPaused] = useState(!!me?.paused);
  const [training, setTraining] = useState(!!me?.training_opt_in);
  const [previews, setPreviews] = useState(me?.push_previews ?? true);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async () => {
    setError(''); setStatus('');
    const h = Number(hour);
    if (!Number.isInteger(h) || h < 0 || h > 23) return setError('The brief hour is a number from 0 to 23.');
    try {
      await api('/settings', { method: 'PATCH', body: {
        assistant_name: name.trim() || null, persona: persona.trim(), timezone: tz.trim() || null, brief_hour: h,
        ideas_enabled: ideas, paused, training_opt_in: training, push_previews: previews,
      } });
      await refresh();
      setStatus('Saved');
    } catch (e) { setError((e as Error).message); }
  };

  const connectGoogle = async () => {
    setError('');
    try {
      const { url } = await api<{ url: string }>('/onboarding/google', { method: 'POST', body: { client: Platform.OS === 'web' ? 'web' : 'app' } });
      if (Platform.OS === 'web') { globalThis.location.href = url; return; }
      await WebBrowser.openAuthSessionAsync(url, Linking.createURL('connected'));
      await refresh();
    } catch (e) { setError((e as Error).message); }
  };

  const disconnect = async () => {
    if (!(await confirm('Disconnect Google?', 'Your assistant stops reading new email and calendar events.', 'Disconnect'))) return;
    await api('/connections/google', { method: 'DELETE' });
    await refresh();
  };

  const deleteAll = async () => {
    if (!(await confirm('Delete everything?', 'This erases your account, memories and history, and disconnects Google. It cannot be undone.', 'Delete everything'))) return;
    try {
      await api('/chat', { method: 'POST', body: { text: 'delete everything' } });
      const r = await api<{ deleted?: boolean }>('/chat', { method: 'POST', body: { text: 'DELETE' } });
      if (r.deleted) await signOut();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <Screen edges={[]}>
      <Section>Your assistant</Section>
      <Field label="Name" value={name} onChangeText={setName} maxLength={60} />
      <Field label="Personality" value={persona} onChangeText={setPersona} maxLength={500} placeholder="Warm, a little witty, replies in Hinglish when I do" />
      <Field label="Time zone" value={tz} onChangeText={setTz} placeholder="Asia/Kolkata" autoCapitalize="none" />
      <Field label="Daily brief hour (0–23)" value={hour} onChangeText={setHour} keyboardType="number-pad" maxLength={2} />
      <Toggle label="Evening ideas" hint="Up to 3 next steps toward your goals" value={ideas} onChange={setIdeas} />
      <Toggle label="Pause messages" hint="Your assistant won't message you first" value={paused} onChange={setPaused} />
      <Toggle label="Show message text in notifications" hint="Turn off to hide it on the lock screen" value={previews} onChange={setPreviews} />
      <Toggle label="Help improve the product" hint="De-identified data only. Never used for ads." value={training} onChange={setTraining} />
      <ErrorText>{error}</ErrorText>
      <Row style={{ marginTop: space.s }}>
        <Button title="Save settings" onPress={save} />
        {status ? <P muted>{status}</P> : null}
      </Row>

      <Section>Account</Section>
      <Card>
        {me?.email ? <P>Email: {me.email}</P> : null}
        {me?.phone && !me.demo ? <P>Phone: {me.phone}</P> : null}
        <P style={{ marginTop: 6 }}>Google: {me?.demo ? 'Sample inbox (demo)' : me?.google || 'Not connected'}</P>
        {!me?.demo ? (
          <Row style={{ marginTop: space.s }}>
            {me?.google ? <Button small kind="ghost" title="Disconnect Google" onPress={disconnect} /> : <Button small title="Connect Google" onPress={connectGoogle} />}
          </Row>
        ) : null}
      </Card>
      <Button kind="ghost" title="Privacy and terms" onPress={async () => { await WebBrowser.openBrowserAsync(`${API_URL}/privacy`); }} style={{ marginTop: space.s }} />
      <Button kind="ghost" title={me?.demo ? 'End the demo' : 'Sign out'} onPress={signOut} style={{ marginTop: space.s }} />
      {!me?.demo ? <Button kind="warn" title="Delete everything" onPress={deleteAll} style={{ marginTop: space.s }} /> : null}
    </Screen>
  );
}
