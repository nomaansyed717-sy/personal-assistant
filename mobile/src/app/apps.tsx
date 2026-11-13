import Ionicons from '@expo/vector-icons/Ionicons';
import * as Linking from 'expo-linking';
import { useFocusEffect } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';

import { Button, Card, Empty, ErrorText, Field, P, Pill, Row, Screen, Section, Text } from '@/components/ui';
import { api, type CatalogApp, type ConnectedApp } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { radius, space, useTheme } from '@/lib/theme';

const ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  zapier: 'flash-outline', notion: 'document-text-outline', linear: 'git-branch-outline', github: 'logo-github',
  stripe: 'card-outline', composio: 'apps-outline', custom: 'link-outline',
};

const client = Platform.OS === 'web' ? 'web' : 'app';

async function signIn(url: string) {
  if (Platform.OS === 'web') { globalThis.location.href = url; return; }
  await WebBrowser.openAuthSessionAsync(url, Linking.createURL('connected'));
}

export default function Apps() {
  const t = useTheme();
  const { me } = useAuth();
  const [catalog, setCatalog] = useState<CatalogApp[]>([]);
  const [apps, setApps] = useState<ConnectedApp[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [c, a] = await Promise.all([api<CatalogApp[]>('/connectors/catalog'), api<ConnectedApp[]>('/connectors')]);
      setCatalog(c); setApps(a);
    } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const pick = (id: string) => { setOpen(o => (o === id ? null : id)); setUrl(''); setToken(''); setError(''); };

  const connect = async (app: CatalogApp) => {
    setBusy(true); setError('');
    try {
      const r = await api<{ connector: ConnectedApp; auth_url: string | null }>('/connectors', {
        method: 'POST', body: { catalog_id: app.id, url: url.trim() || undefined, token: token.trim() || undefined, client },
      });
      if (r.auth_url) await signIn(r.auth_url);
      setOpen(null); setUrl(''); setToken('');
      await load();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  const again = async (a: ConnectedApp) => {
    try {
      const r = await api<{ auth_url: string }>(`/connectors/${a.id}/signin?client=${client}`, { method: 'POST' });
      await signIn(r.auth_url); await load();
    } catch (e) { setError((e as Error).message); }
  };
  const refresh = async (a: ConnectedApp) => { await api(`/connectors/${a.id}/refresh`, { method: 'POST' }); await load(); };
  const remove = async (a: ConnectedApp) => { await api(`/connectors/${a.id}`, { method: 'DELETE' }); await load(); };

  if (me?.demo) {
    return (
      <Screen edges={[]}>
        <Empty>Connected apps need your own account. Sign out of the demo and sign in with your email to add Notion, GitHub, Zapier and more.</Empty>
      </Screen>
    );
  }

  return (
    <Screen edges={[]}>
      <P muted>Let your assistant use your other apps. It reads freely, and anything that creates, changes or sends something waits for your yes in Approvals.</P>
      {!open ? <ErrorText>{error}</ErrorText> : null}

      <Section>Connected</Section>
      {apps && !apps.length ? <Empty>Nothing connected yet. Pick an app below.</Empty> : null}
      {apps?.map(a => (
        <Card key={a.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Row style={{ flex: 1 }}>
              <View style={[styles.icon, { backgroundColor: t.soft }]}><Ionicons name={ICONS[a.catalog_id] || 'link-outline'} size={18} color={t.text} /></View>
              <View style={{ flex: 1 }}>
                <P bold>{a.name}</P>
                <P small muted>{a.status === 'active' ? `${a.tool_count} tools · ${a.tools.filter(x => x.read_only).length} read-only` : a.url_host}</P>
              </View>
            </Row>
            <Pill label={a.status === 'active' ? 'Connected' : a.status === 'needs_auth' ? 'Sign in' : 'Problem'} tone={a.status === 'active' ? 'good' : 'accent'} />
          </Row>
          {a.last_error && a.status === 'error' ? <P small muted style={{ marginTop: 6 }}>{a.last_error}</P> : null}
          <Row style={{ marginTop: space.m }}>
            {a.status === 'needs_auth' && a.auth === 'oauth' ? <Button small title="Sign in" onPress={() => again(a)} style={{ flex: 1 }} /> : null}
            {a.status !== 'needs_auth' ? <Button small kind="ghost" title="Refresh" onPress={() => refresh(a)} style={{ flex: 1 }} /> : null}
            <Button small kind="warn" title="Remove" onPress={() => remove(a)} style={{ flex: 1 }} />
          </Row>
        </Card>
      ))}

      <Section>Add an app</Section>
      {catalog.map(app => (
        <View key={app.id} style={[styles.tile, { backgroundColor: t.card, borderColor: open === app.id ? t.text : t.line }]}>
          <Pressable accessibilityRole="button" onPress={() => pick(app.id)} style={styles.tileHead}>
            <View style={[styles.icon, { backgroundColor: t.soft }]}><Ionicons name={ICONS[app.id] || 'link-outline'} size={18} color={t.text} /></View>
            <View style={{ flex: 1 }}>
              <Text style={{ color: t.text, fontSize: 15.5, fontWeight: '600' }}>{app.name}</Text>
              <Text style={{ color: t.muted, fontSize: 13 }}>{app.blurb}</Text>
            </View>
            <Ionicons name={open === app.id ? 'chevron-up' : 'add'} size={18} color={t.muted} />
          </Pressable>
          {open === app.id ? (
            <View style={{ paddingHorizontal: space.l, paddingBottom: space.l }}>
              {app.help ? <P small muted style={{ marginBottom: space.m }}>{app.help}</P> : null}
              {!app.url ? <Field label="Server URL" value={url} onChangeText={setUrl} autoCapitalize="none" autoCorrect={false} placeholder="https://…" /> : null}
              {app.auth === 'token' ? (
                <Field label={app.id === 'custom' ? 'Token (if it needs one)' : 'Token'} value={token} onChangeText={setToken}
                  autoCapitalize="none" autoCorrect={false} secureTextEntry placeholder="Paste it here" />
              ) : null}
              {error ? <ErrorText>{error}</ErrorText> : null}
              <Button title={app.auth === 'oauth' ? `Sign in to ${app.name}` : 'Connect'} busy={busy}
                disabled={(!app.url && url.trim().length < 10) || (app.auth === 'token' && app.id !== 'custom' && token.trim().length < 8)}
                onPress={() => connect(app)} />
            </View>
          ) : null}
        </View>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  icon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', marginRight: space.s },
  tile: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.l, marginBottom: space.s, overflow: 'hidden' },
  tileHead: { flexDirection: 'row', alignItems: 'center', gap: space.s, padding: space.l },
});
