import * as Localization from 'expo-localization';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, ErrorText, Field } from '@/components/ui';
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
      setNote(r.sent_to === 'email' ? `We emailed a 6-digit code to ${ident.trim()}.` : `We texted a 6-digit code to ${ident.trim()}.`);
      setStep('code');
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const verify = async () => {
    setError('');
    try {
      const r = await api<{ token: string }>('/auth/verify', { method: 'POST', body: { ...who(), code: code.trim(), client: 'app' } });
      await signIn(r.token);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const demo = async () => {
    setError('');
    try {
      const r = await api<{ token: string }>('/demo/start', { method: 'POST', body: { tz: deviceTz(), client: 'app' } });
      await signIn(r.token);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ink }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.wrap} keyboardShouldPersistTaps="handled">
          <Text style={styles.brand}>Aide</Text>
          <Text style={styles.tagline}>Your chief of staff, in your pocket.</Text>
          <View style={[styles.card, { backgroundColor: t.card }]}>
            {step === 'start' ? (
              <>
                <Text style={[styles.h, { color: t.text }]}>Sign in or create an account</Text>
                <Text style={{ color: t.muted, marginBottom: space.m }}>We'll send you a one-time code. No password.</Text>
                <View style={[styles.seg, { backgroundColor: t.bg }]} accessibilityRole="tablist">
                  {(['email', 'phone'] as const).map(m => (
                    <Pressable
                      key={m}
                      accessibilityRole="tab"
                      accessibilityState={{ selected: method === m }}
                      onPress={() => { setMethod(m); setIdent(''); setError(''); }}
                      style={[styles.segBtn, method === m && { backgroundColor: t.card }]}>
                      <Text style={{ color: method === m ? t.text : t.muted, fontWeight: '600' }}>{m === 'email' ? 'Email' : 'Phone'}</Text>
                    </Pressable>
                  ))}
                </View>
                <Field
                  label={method === 'email' ? 'Email address' : 'Mobile number, with country code'}
                  value={ident}
                  onChangeText={setIdent}
                  placeholder={method === 'email' ? 'you@example.com' : '+91 98765 43210'}
                  keyboardType={method === 'email' ? 'email-address' : 'phone-pad'}
                  autoCapitalize="none"
                  autoComplete={method === 'email' ? 'email' : 'tel'}
                  textContentType={method === 'email' ? 'emailAddress' : 'telephoneNumber'}
                  onSubmitEditing={sendCode}
                  returnKeyType="send"
                />
                <ErrorText>{error}</ErrorText>
                <Button title="Send code" onPress={sendCode} disabled={ident.trim().length < 5} />
              </>
            ) : (
              <>
                <Text style={[styles.h, { color: t.text }]}>Enter your code</Text>
                <Text style={{ color: t.muted, marginBottom: space.m }}>{note}</Text>
                <Field
                  label="6-digit code"
                  value={code}
                  onChangeText={v => setCode(v.replace(/\D/g, '').slice(0, 6))}
                  keyboardType="number-pad"
                  autoComplete="one-time-code"
                  textContentType="oneTimeCode"
                  maxLength={6}
                  autoFocus
                  onSubmitEditing={verify}
                  style={{ fontSize: 24, letterSpacing: 8, textAlign: 'center' }}
                />
                <ErrorText>{error}</ErrorText>
                <Button title="Continue" onPress={verify} disabled={code.length !== 6} />
                <Button title="Use a different email or number" kind="ghost" onPress={() => { setStep('start'); setCode(''); setError(''); }} style={{ marginTop: space.s }} />
              </>
            )}
          </View>
          <View style={styles.demo}>
            <Text style={{ color: '#C9DCD9', textAlign: 'center', marginBottom: space.s }}>
              Just looking? Try the real assistant on a sample inbox. Nothing is sent, booked or paid.
            </Text>
            <Button title="Try the live demo" kind="accent" onPress={demo} />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flexGrow: 1, justifyContent: 'center', padding: space.xl, maxWidth: 480, width: '100%', alignSelf: 'center' },
  brand: { color: '#fff', fontSize: 40, fontWeight: '700', letterSpacing: -0.5 },
  tagline: { color: '#C9DCD9', fontSize: 17, marginBottom: space.xl },
  card: { borderRadius: radius.l, padding: space.xl },
  h: { fontSize: 21, fontWeight: '700', marginBottom: 4 },
  seg: { flexDirection: 'row', borderRadius: radius.pill, padding: 3, marginBottom: space.m },
  segBtn: { flex: 1, alignItems: 'center', paddingVertical: 9, borderRadius: radius.pill },
  demo: { marginTop: space.xl },
});
