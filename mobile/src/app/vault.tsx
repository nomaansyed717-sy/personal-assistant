import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

import { Button, Card, Empty, ErrorText, Field, P, Row, Screen, Section } from '@/components/ui';
import { api, type VaultItem } from '@/lib/api';

export default function Vault() {
  const [items, setItems] = useState<VaultItem[] | null>(null);
  const [label, setLabel] = useState('');
  const [site, setSite] = useState('');
  const [user, setUser] = useState('');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setItems(await api<VaultItem[]>('/vault')); } catch (e) { setError((e as Error).message); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  return (
    <Screen edges={[]}>
      <P muted>Logins the secure browser can use for you. They're encrypted, the AI never sees them, and only the browser types them in. Never send passwords in chat.</P>
      <Section>Saved logins</Section>
      {items && !items.length ? <Empty>No saved logins.</Empty> : null}
      {items?.map(v => (
        <Card key={v.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <P style={{ flex: 1 }}>{v.label} ({v.site})</P>
            <Button small kind="ghost" title="Remove" onPress={async () => { await api(`/vault/${v.id}`, { method: 'DELETE' }); await load(); }} />
          </Row>
        </Card>
      ))}
      <Section>Add a login</Section>
      <Field label="Name" value={label} onChangeText={setLabel} placeholder="Amazon" />
      <Field label="Website" value={site} onChangeText={setSite} placeholder="amazon.in" autoCapitalize="none" keyboardType="url" />
      <Field label="Username or email" value={user} onChangeText={setUser} autoCapitalize="none" autoComplete="off" />
      <Field label="Password" value={secret} onChangeText={setSecret} secureTextEntry autoComplete="off" textContentType="none" />
      <ErrorText>{error}</ErrorText>
      <Button title="Save login" disabled={!label.trim() || site.trim().length < 3 || !user.trim() || !secret} onPress={async () => {
        setError('');
        try {
          await api('/vault', { method: 'POST', body: { label: label.trim(), site: site.trim(), username: user.trim(), secret } });
          setLabel(''); setSite(''); setUser(''); setSecret('');
          await load();
        } catch (e) { setError((e as Error).message); }
      }} />
    </Screen>
  );
}
