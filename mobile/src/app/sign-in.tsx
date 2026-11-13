import * as Localization from 'expo-localization';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Wordmark } from '@/components/brand';
import { Button, ErrorText, Field, Text } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

const deviceTz = () => Localization.getCalendars()[0]?.timeZone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export default function SignIn() {
  const t = useTheme();
  const { signIn } = useAuth();
  const [method, setMethod] = useState<'email' | 'phone'>('email');
  const [ident, setIdent] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'start' | 'code'>('start');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  const who = () => (method === 'email' ? { email: ident.trim() } : { phone: ident.trim() });

  const sendCode = async () => {
    setError('');
    try {
      const r = await api<{ sent_to: string }>('/auth/start', { method: 'POST', body: { ...who(), tz: deviceTz() } });
      setNote(r.sent_to === 'email' ? `Sent to ${ident.trim()}` : `Texted to ${ident.trim()}`);
      setStep('code');
    } catch (e) { setError((e as Error).message); }
  };

  const verify = async () => {
    setError('');
    try {
      const r = await api<{ token: string }>('/auth/verify', { method: 'POST', body: { ...who(), code: code.trim(), client: 'app' } });
      await signIn(r.token);
    } catch (e) { setError((e as Error).message); }
  };

  const demo = async () => {
    setError('');
    try {
      const r = await api<{ token: string }>('/demo/start', { method: 'POST', body: { tz: deviceTz(), client: 'app' } });
      await signIn(r.token);
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.wrap} keyboardShouldPersistTaps="handled">
          <View style={{ gap: space.m, marginBottom: 40 }}>
            <Wordmark size={40} />
            <Text style={[styles.headline, { color: t.text }]}>Your chief of staff,{'\n'}in your pocket.</Text>
            <Text style={{ color: t.muted, fontSize: 15.5, lineHeight: 23 }}>
              It keeps track of what you’ve promised, books what you ask for, and always asks before it pays or sends.
            </Text>
          </View>

          {step === 'start' ? (
            <View>
              <View style={[styles.seg, { backgroundColor: t.soft }]} accessibilityRole="tablist">
                {(['email', 'phone'] as const).map(m => (
                  <Pressable key={m} accessibilityRole="tab" accessibilityState={{ selected: method === m }}
                    onPress={() => { setMethod(m); setIdent(''); setError(''); }}
                    style={[styles.segBtn, method === m && { backgroundColor: t.card }]}>
                    <Text style={{ color: method === m ? t.text : t.muted, fontWeight: '600', fontSize: 14 }}>{m === 'email' ? 'Email' : 'Phone'}</Text>
                  </Pressable>
                ))}
              </View>
              <Field
                value={ident}
                onChangeText={setIdent}
                placeholder={method === 'email' ? 'you@example.com' : '+91 98765 43210'}
                keyboardType={method === 'email' ? 'email-address' : 'phone-pad'}
                autoCapitalize="none"
                autoComplete={method === 'email' ? 'email' : 'tel'}
                textContentType={method === 'email' ? 'emailAddress' : 'telephoneNumber'}
                onSubmitEditing={sendCode}
                returnKeyType="send"
                accessibilityLabel={method === 'email' ? 'Email address' : 'Mobile number'}
              />
              <ErrorText>{error}</ErrorText>
              <Button title="Continue" onPress={sendCode} disabled={ident.trim().length < 5} />
              <Text style={{ color: t.muted, fontSize: 13, textAlign: 'center', marginTop: space.m }}>
                We’ll send a one-time code. No password, ever.
              </Text>
            </View>
          ) : (
            <View>
              <Text style={{ color: t.text, fontSize: 20, fontWeight: '600', letterSpacing: -0.4 }}>Enter the 6-digit code</Text>
              <Text style={{ color: t.muted, marginTop: 4, marginBottom: space.l }}>{note}</Text>
              <Field
                value={code}
                onChangeText={v => setCode(v.replace(/\D/g, '').slice(0, 6))}
                keyboardType="number-pad"
                autoComplete="one-time-code"
                textContentType="oneTimeCode"
                maxLength={6}
                autoFocus
                onSubmitEditing={verify}
                placeholder="••••••"
                accessibilityLabel="6-digit code"
                style={{ fontSize: 26, letterSpacing: 12, textAlign: 'center', fontWeight: '600' }}
              />
              <ErrorText>{error}</ErrorText>
              <Button title="Sign in" onPress={verify} disabled={code.length !== 6} />
              <Button title="Use a different email or number" kind="plain" onPress={() => { setStep('start'); setCode(''); setError(''); }} style={{ marginTop: space.s }} />
            </View>
          )}

          <Pressable accessibilityRole="button" onPress={demo} style={({ pressed }) => [styles.demo, { borderColor: t.line, opacity: pressed ? 0.6 : 1 }]}>
            <View style={[styles.dot, { backgroundColor: t.marigold }]} />
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.text, fontWeight: '600', fontSize: 14.5 }}>Try the live demo</Text>
              <Text style={{ color: t.muted, fontSize: 13 }}>A sample inbox. Nothing is sent, booked or paid.</Text>
            </View>
            <Text style={{ color: t.muted, fontSize: 18 }}>→</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 32, maxWidth: 460, width: '100%', alignSelf: 'center' },
  headline: { fontSize: 30, lineHeight: 36, fontWeight: '700', letterSpacing: -1 },
  seg: { flexDirection: 'row', borderRadius: radius.pill, padding: 4, marginBottom: space.m },
  segBtn: { flex: 1, alignItems: 'center', paddingVertical: 9, borderRadius: radius.pill },
  demo: { marginTop: 36, flexDirection: 'row', alignItems: 'center', gap: space.m, borderWidth: 1, borderRadius: radius.l, padding: space.l },
  dot: { width: 10, height: 10, borderRadius: 5 },
});
