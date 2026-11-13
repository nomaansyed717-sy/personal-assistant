import * as Linking from 'expo-linking';
import * as Localization from 'expo-localization';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Wordmark } from '@/components/brand';
import { Button, ErrorText, Field, Text } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

const PROMISES = [
  'Everything is encrypted with a key unique to you.',
  'Nothing goes to someone new, and nothing is booked or bought, without your yes.',
  'Your data is never used for ads. Delete everything any time.',
];

export default function Setup() {
  const t = useTheme();
  const { me, refresh, signOut } = useAuth();
  const [name, setName] = useState(me?.name || '');
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState('');
  const state = me?.onboarding_state;

  // While the first sync runs, check back every few seconds.
  useEffect(() => {
    if (state !== 'syncing') return;
    const id = setInterval(() => { void refresh(); }, 4000);
    return () => clearInterval(id);
  }, [state, refresh]);

  const consent = async () => {
    setError('');
    try {
      const tz = Localization.getCalendars()[0]?.timeZone || undefined;
      await api('/onboarding/consent', { method: 'POST', body: { accept: true, name: name.trim() || null, timezone: tz } });
      await refresh();
    } catch (e) { setError((e as Error).message); }
  };

  const connect = async () => {
    setError('');
    try {
      const { url } = await api<{ url: string }>('/onboarding/google', { method: 'POST', body: { client: Platform.OS === 'web' ? 'web' : 'app' } });
      if (Platform.OS === 'web') { globalThis.location.href = url; return; }
      await WebBrowser.openAuthSessionAsync(url, Linking.createURL('connected'));
      await refresh();
    } catch (e) { setError((e as Error).message); }
  };

  const skip = async () => {
    setError('');
    try { await api('/onboarding/skip', { method: 'POST' }); await refresh(); }
    catch (e) { setError((e as Error).message); }
  };

  const step = state === 'awaiting_consent' ? 1 : state === 'awaiting_connect' ? 2 : 3;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }}>
      <ScrollView contentContainerStyle={styles.wrap} keyboardShouldPersistTaps="handled">
        <Wordmark size={28} />
        <View style={styles.card}>
          <View style={styles.dots} accessibilityLabel={`Step ${step} of 3`}>
            {[1, 2, 3].map(i => <View key={i} style={[styles.dot, { backgroundColor: i <= step ? t.text : t.soft, width: i === step ? 28 : 8 }]} />)}
          </View>

          {state === 'awaiting_consent' && (
            <>
              <Text style={[styles.h, { color: t.text }]}>Welcome</Text>
              <Text style={{ color: t.muted, marginBottom: space.m }}>Before we start, here’s how your assistant treats your data.</Text>
              <View style={[styles.promises, { backgroundColor: t.soft }]}>
                {PROMISES.map(p => (
                  <View key={p} style={styles.li}>
                    <View style={[styles.tick, { backgroundColor: t.card }]}><Text style={{ color: t.leaf, fontWeight: '700', fontSize: 12 }}>✓</Text></View>
                    <Text style={{ color: t.text, flex: 1, lineHeight: 21, fontSize: 14.5 }}>{p}</Text>
                  </View>
                ))}
              </View>
              <View style={{ height: space.m }} />
              <Field label="What should it call you?" value={name} onChangeText={setName} placeholder="Your first name" autoComplete="given-name" />
              <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: agree }} onPress={() => setAgree(!agree)} style={styles.check}>
                <View style={[styles.box, { borderColor: agree ? t.ink : t.muted, backgroundColor: agree ? t.ink : 'transparent' }]}>
                  {agree ? <Text style={{ color: t.onInk, fontWeight: '700', fontSize: 13 }}>✓</Text> : null}
                </View>
                <Text style={{ color: t.text, flex: 1 }}>I agree to the privacy policy and terms.</Text>
              </Pressable>
              <Pressable accessibilityRole="link" onPress={() => { void WebBrowser.openBrowserAsync(`${API_URL}/privacy`); }} style={{ marginLeft: 36, marginBottom: space.s }}>
                <Text style={{ color: t.ink2, fontWeight: '600' }}>Read the privacy policy and terms</Text>
              </Pressable>
              <ErrorText>{error}</ErrorText>
              <Button title="Agree and continue" onPress={consent} disabled={!agree} />
            </>
          )}

          {state === 'awaiting_connect' && (
            <>
              <Text style={[styles.h, { color: t.text }]}>Connect your email</Text>
              <Text style={{ color: t.muted, marginBottom: space.l, lineHeight: 21 }}>
                Connect Gmail and Google Calendar so your assistant can find what you’ve promised, what you’re owed, and what’s on today. It only sends what you approve.
              </Text>
              <ErrorText>{error}</ErrorText>
              <Button title="Connect Google" onPress={connect} />
              <Button title="Skip for now" kind="ghost" onPress={skip} style={{ marginTop: space.s }} />
              <Text style={{ color: t.muted, fontSize: 13, marginTop: space.m }}>Outlook and Zoho Mail are coming.</Text>
            </>
          )}

          {state === 'syncing' && (
            <>
              <Text style={[styles.h, { color: t.text }]}>Reading your last few weeks</Text>
              <Text style={{ color: t.muted, marginBottom: space.l, lineHeight: 21 }}>
                This takes a few minutes. Your first brief appears as soon as it’s ready, and we’ll notify you.
              </Text>
              <ActivityIndicator color={t.text} />
            </>
          )}
        </View>
        <Pressable accessibilityRole="button" onPress={signOut} style={{ marginTop: space.l, alignSelf: 'center', padding: space.s }}>
          <Text style={{ color: t.muted, fontWeight: '500' }}>Sign out</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 32, maxWidth: 460, width: '100%', alignSelf: 'center', gap: 32 },
  card: {},
  dots: { flexDirection: 'row', gap: 6, marginBottom: space.xl },
  dot: { height: 6, borderRadius: 3 },
  h: { fontSize: 28, lineHeight: 34, fontWeight: '700', letterSpacing: -0.9, marginBottom: 8 },
  promises: { borderRadius: radius.l, padding: space.l, gap: space.m },
  tick: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  li: { flexDirection: 'row', gap: space.m, alignItems: 'flex-start' },
  check: { flexDirection: 'row', alignItems: 'center', gap: space.m, marginBottom: space.s },
  box: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
});
