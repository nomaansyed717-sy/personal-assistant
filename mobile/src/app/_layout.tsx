import * as Notifications from 'expo-notifications';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, router } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Platform, useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { registerPush } from '@/lib/push';
import { useTheme } from '@/lib/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <Navigator />
      </AuthProvider>
    </SafeAreaProvider>
  );
}

function Navigator() {
  const { loading, token, me } = useAuth();
  const scheme = useColorScheme();
  const t = useTheme();
  const signedIn = !!token && !!me;
  const ready = signedIn && (me.demo || me.onboarding_state === 'active');
  const inSetup = signedIn && !ready;

  useEffect(() => {
    if (!loading) SplashScreen.hideAsync().catch(() => {});
  }, [loading]);

  // Push: register once the account is set up; a tap on a notification opens the chat (or approvals).
  useEffect(() => {
    if (!ready || me?.demo || Platform.OS === 'web') return;
    void registerPush();
    const sub = Notifications.addNotificationResponseReceivedListener(response => {
      const kind = response.notification.request.content.data?.kind;
      router.push(kind === 'approval' ? '/approvals' : kind === 'phone_task' ? '/agent' : '/chat');
    });
    return () => sub.remove();
  }, [ready, me?.demo]);

  if (loading) return <Loading />;

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = { ...base, colors: { ...base.colors, background: t.bg, card: t.card, text: t.text, border: t.line, primary: t.ink2 } };
  const header = { headerStyle: { backgroundColor: t.card }, headerTintColor: t.text, headerShadowVisible: false, headerBackTitle: 'Back' };

  return (
    <ThemeProvider value={navTheme}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack screenOptions={{ ...header, contentStyle: { backgroundColor: t.bg } }}>
        <Stack.Protected guard={!signedIn}>
          <Stack.Screen name="sign-in" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={inSetup}>
          <Stack.Screen name="setup" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={ready}>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="activity" options={{ title: 'Activity' }} />
          <Stack.Screen name="goals" options={{ title: 'Goals' }} />
          <Stack.Screen name="tasks" options={{ title: 'Standing tasks' }} />
          <Stack.Screen name="memory" options={{ title: 'Memory' }} />
          <Stack.Screen name="skills" options={{ title: 'Skills' }} />
          <Stack.Screen name="money" options={{ title: 'Money' }} />
          <Stack.Screen name="vault" options={{ title: 'Vault' }} />
          <Stack.Screen name="settings" options={{ title: 'Settings' }} />
        </Stack.Protected>
        <Stack.Screen name="connected" options={{ headerShown: false }} />
      </Stack>
    </ThemeProvider>
  );
}
