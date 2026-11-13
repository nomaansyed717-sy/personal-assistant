import Ionicons from '@expo/vector-icons/Ionicons';
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from 'expo-audio';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Chip, Rich, Text, TextInput } from '@/components/ui';
import { api, upload, type ChatMessage, type UploadFile } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useBadge } from '@/lib/badge';
import { radius, space, useTheme } from '@/lib/theme';

const SUGGESTIONS = ["What's open?", 'What are you planning?', 'Plan my week around my goals', 'Find subscriptions I can cancel', 'What did you do today?'];

type Item = ChatMessage | { id: number; from: 'assistant' | 'me'; text: string; at?: string; pending: true; channel?: string };

export default function Chat() {
  const t = useTheme();
  const { me } = useAuth();
  const badge = useBadge();
  const params = useLocalSearchParams<{ draft?: string }>();
  const [msgs, setMsgs] = useState<Item[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [attachOpen, setAttachOpen] = useState(false);
  const list = useRef<FlatList<Item>>(null);
  const lastId = useRef(0);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const rec = useAudioRecorderState(recorder);

  const load = useCallback(async () => {
    try {
      const m = await api<ChatMessage[]>('/messages?limit=100');
      setMsgs(m);
      lastId.current = m.length ? m[m.length - 1].id : 0;
    } catch {}
  }, []);

  const poll = useCallback(async () => {
    if (busy) return;
    try {
      const fresh = await api<ChatMessage[]>(`/messages?after=${lastId.current}`);
      if (fresh.length) {
        setMsgs(prev => [...prev.filter(x => !('pending' in x)), ...fresh]);
        lastId.current = fresh[fresh.length - 1].id;
        void badge.refresh();
      }
    } catch {}
  }, [busy, badge]);

  useFocusEffect(useCallback(() => {
    void load();
    const id = setInterval(poll, 4000);
    return () => clearInterval(id);
  }, [load, poll]));

  useEffect(() => {
    if (params.draft) setText(params.draft);
  }, [params.draft]);

  const optimistic = (from: 'me' | 'assistant', body: string) =>
    setMsgs(prev => [...prev, { id: -Date.now() - Math.random(), from, text: body, pending: true }]);

  const afterReply = async () => {
    await load();
    await badge.refresh();
  };

  const send = async (body?: string) => {
    const value = (body ?? text).trim();
    if (!value || busy) return;
    setText('');
    optimistic('me', value);
    setBusy('Thinking…');
    try {
      const r = await api<{ reply: string; deleted?: boolean }>('/chat', { method: 'POST', body: { text: value } });
      if (r.deleted) return;
      await afterReply();
    } catch (e) {
      optimistic('assistant', (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const sendFile = async (file: UploadFile, voice = false) => {
    setAttachOpen(false);
    const caption = voice ? '' : text.trim();
    if (!voice) setText('');
    optimistic('me', voice ? '🎤 Voice note' : `📎 ${file.name}${caption ? '\n' + caption : ''}`);
    setBusy(voice ? 'Listening…' : 'Reading…');
    try {
      await upload(file, { caption, voice });
      await afterReply();
    } catch (e) {
      optimistic('assistant', (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const pickPhoto = async (camera: boolean) => {
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.7 };
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return optimistic('assistant', 'Camera permission is off. Turn it on in Android Settings to send photos.');
    }
    const r = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (r.canceled || !r.assets[0]) return;
    const a = r.assets[0];
    await sendFile({ uri: a.uri, name: a.fileName || 'photo.jpg', type: a.mimeType || 'image/jpeg' });
  };

  const pickFile = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'text/plain', 'image/*'], copyToCacheDirectory: true });
    if (r.canceled || !r.assets[0]) return;
    const a = r.assets[0];
    await sendFile({ uri: a.uri, name: a.name, type: a.mimeType || 'application/octet-stream' });
  };

  const toggleRecording = async () => {
    if (rec.isRecording) {
      await recorder.stop();
      const uri = recorder.uri;
      if (uri) await sendFile({ uri, name: Platform.OS === 'web' ? 'voice.webm' : 'voice.m4a', type: Platform.OS === 'web' ? 'audio/webm' : 'audio/mp4' }, true);
      return;
    }
    const perm = await AudioModule.requestRecordingPermissionsAsync();
    if (!perm.granted) return optimistic('assistant', 'Microphone permission is off. Turn it on in Settings to send voice notes.');
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
  };

  const renderItem = ({ item }: { item: Item }) => {
    const mine = item.from === 'me';
    return (
      <View style={[styles.bubble, mine ? [styles.me, { backgroundColor: t.bubbleMe }] : [styles.them, { backgroundColor: t.bubbleThem, borderColor: t.line }]]}>
        <Rich text={item.text} color={mine ? t.bubbleMeText : t.text} />
        {'at' in item && item.at ? (
          <Text style={[styles.meta, { color: mine ? t.bubbleMeText : t.muted, opacity: mine ? 0.6 : 1 }]}>
            {new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}{item.channel === 'demo' ? ' · demo' : ''}
          </Text>
        ) : null}
      </View>
    );
  };

  const secs = Math.floor((rec.durationMillis || 0) / 1000);
  const name = me?.assistant_name || 'Aide';

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={styles.header}>
        <View style={[styles.avatar, { backgroundColor: t.ink }]}>
          <Text style={{ color: t.onInk, fontWeight: '700', fontSize: 16 }}>{name[0].toLowerCase()}</Text>
          <View style={[styles.avatarDot, { backgroundColor: t.marigold, borderColor: t.bg }]} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: t.text, fontWeight: '600', fontSize: 16.5, letterSpacing: -0.3 }}>{name}</Text>
          <Text style={{ color: busy ? t.ink2 : t.muted, fontSize: 12.5 }}>{busy ? busy : me?.demo ? 'Live demo · nothing is really sent' : 'Asks before anything important'}</Text>
        </View>
      </View>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={0}>
        <FlatList
          ref={list}
          data={msgs}
          keyExtractor={m => String(m.id)}
          renderItem={renderItem}
          contentContainerStyle={styles.thread}
          showsVerticalScrollIndicator={false}
          // Open at the newest message. scrollToEnd is unreliable on web before cells are measured, so scroll
          // to the reported content height on the next frame instead.
          onContentSizeChange={(_w, h) => requestAnimationFrame(() => list.current?.scrollToOffset({ offset: h, animated: false }))}
          ListEmptyComponent={
            <View style={{ alignItems: 'center', marginTop: 80, gap: 6 }}>
              <Text style={{ color: t.text, fontSize: 20, fontWeight: '600', letterSpacing: -0.4 }}>What can I take off your plate?</Text>
              <Text style={{ color: t.muted }}>Ask anything, or try a suggestion below.</Text>
            </View>
          }
        />
        {msgs.length < 4 && !busy ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.suggest} style={{ flexGrow: 0 }}>
            {SUGGESTIONS.map(s => <Chip key={s} label={s} onPress={() => send(s)} />)}
          </ScrollView>
        ) : null}
        {attachOpen ? (
          <View style={styles.attach}>
            {([['camera-outline', 'Camera', () => pickPhoto(true)], ['image-outline', 'Photo', () => pickPhoto(false)], ['document-text-outline', 'File', pickFile]] as const).map(([ic, label, fn]) => (
              <Pressable key={label} onPress={fn} style={({ pressed }) => [styles.attachBtn, { backgroundColor: t.soft, opacity: pressed ? 0.6 : 1 }]}>
                <Ionicons name={ic} size={22} color={t.text} />
                <Text style={{ color: t.text, fontSize: 12.5, fontWeight: '500' }}>{label}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        <View style={styles.composer}>
          <View style={[styles.field, { backgroundColor: t.card, borderColor: rec.isRecording ? t.rose : t.line }]}>
            <Pressable accessibilityLabel="Attach a photo or file" onPress={() => setAttachOpen(o => !o)} style={styles.inlineIcon} hitSlop={8}>
              <Ionicons name={attachOpen ? 'close' : 'add'} size={24} color={t.muted} />
            </Pressable>
            {rec.isRecording ? (
              <View style={styles.recording}>
                <View style={[styles.dot, { backgroundColor: t.rose }]} />
                <Text style={{ color: t.text, fontVariant: ['tabular-nums'] }}>{Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')}</Text>
                <Text style={{ color: t.muted }}>Tap stop to send</Text>
              </View>
            ) : (
              <TextInput
                value={text}
                onChangeText={setText}
                placeholder={`Message ${name}`}
                placeholderTextColor={t.muted}
                multiline
                style={[styles.input, { color: t.text }]}
                accessibilityLabel="Message"
              />
            )}
            {text.trim() && !rec.isRecording ? (
              <Pressable accessibilityLabel="Send" onPress={() => send()} disabled={!!busy} style={[styles.send, { backgroundColor: t.ink, opacity: busy ? 0.4 : 1 }]}>
                <Ionicons name="arrow-up" size={20} color={t.onInk} />
              </Pressable>
            ) : (
              <Pressable
                accessibilityLabel={rec.isRecording ? 'Stop and send voice note' : 'Record a voice note'}
                onPress={toggleRecording}
                disabled={!!busy}
                style={[styles.send, { backgroundColor: rec.isRecording ? t.rose : t.soft }]}>
                <Ionicons name={rec.isRecording ? 'stop' : 'mic-outline'} size={20} color={rec.isRecording ? '#FFFFFF' : t.text} />
              </Pressable>
            )}
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: space.m, paddingHorizontal: 20, paddingVertical: space.m },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  avatarDot: { position: 'absolute', right: -1, bottom: -1, width: 13, height: 13, borderRadius: 7, borderWidth: 2 },
  thread: { paddingHorizontal: 16, paddingVertical: space.m, gap: 6, flexGrow: 1, maxWidth: 760, width: '100%', alignSelf: 'center' },
  bubble: { maxWidth: '84%', paddingVertical: 10, paddingHorizontal: 14, borderRadius: 20 },
  me: { alignSelf: 'flex-end', borderBottomRightRadius: 6 },
  them: { alignSelf: 'flex-start', borderWidth: StyleSheet.hairlineWidth, borderBottomLeftRadius: 6 },
  meta: { fontSize: 11, marginTop: 4 },
  suggest: { gap: space.s, paddingHorizontal: 16, paddingVertical: space.s, alignItems: 'center' },
  attach: { flexDirection: 'row', gap: space.s, paddingHorizontal: 16, paddingBottom: space.s },
  attachBtn: { flex: 1, alignItems: 'center', gap: 6, paddingVertical: 14, borderRadius: radius.m },
  composer: { paddingHorizontal: 12, paddingTop: 4, paddingBottom: 10 },
  field: { flexDirection: 'row', alignItems: 'flex-end', borderWidth: StyleSheet.hairlineWidth, borderRadius: 26, padding: 5, gap: 4 },
  inlineIcon: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  input: { flex: 1, minHeight: 40, maxHeight: 140, paddingHorizontal: 4, paddingTop: 10, paddingBottom: 10, fontSize: 16 },
  send: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  recording: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.s, minHeight: 40 },
  dot: { width: 9, height: 9, borderRadius: 5 },
});
