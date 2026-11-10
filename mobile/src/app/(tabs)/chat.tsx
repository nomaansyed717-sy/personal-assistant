import Ionicons from '@expo/vector-icons/Ionicons';
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder, useAudioRecorderState } from 'expo-audio';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Chip, Rich, when } from '@/components/ui';
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
      <View style={[styles.bubble, mine ? [styles.me, { backgroundColor: t.bubbleMe }] : [styles.them, { backgroundColor: t.card, borderColor: t.line }]]}>
        <Rich text={item.text} color={mine ? t.bubbleMeText : t.text} />
        {'at' in item && item.at ? (
          <Text style={[styles.meta, { color: mine ? 'rgba(255,255,255,.7)' : t.muted }]}>
            {when(item.at)}{item.channel === 'demo' ? ' · demo' : ''}
          </Text>
        ) : null}
      </View>
    );
  };

  const secs = Math.floor((rec.durationMillis || 0) / 1000);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={[styles.header, { borderBottomColor: t.line, backgroundColor: t.card }]}>
        <View style={[styles.avatar, { backgroundColor: t.marigold }]}><Text style={styles.avatarText}>{(me?.assistant_name || 'A')[0]}</Text></View>
        <View>
          <Text style={{ color: t.text, fontWeight: '700', fontSize: 17 }}>{me?.assistant_name || 'Aide'}</Text>
          <Text style={{ color: t.muted, fontSize: 12 }}>{busy ? busy : me?.demo ? 'Live demo · nothing is really sent' : 'Asks before anything important'}</Text>
        </View>
      </View>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={0}>
        <FlatList
          ref={list}
          data={msgs}
          keyExtractor={m => String(m.id)}
          renderItem={renderItem}
          contentContainerStyle={styles.thread}
          onContentSizeChange={() => list.current?.scrollToEnd({ animated: false })}
          ListEmptyComponent={<Text style={{ color: t.muted, textAlign: 'center', marginTop: space.xxl }}>Say hello, or try a suggestion below.</Text>}
        />
        {msgs.length < 4 && !busy ? (
          <View style={styles.suggest}>
            {SUGGESTIONS.map(s => <Chip key={s} label={s} onPress={() => send(s)} />)}
          </View>
        ) : null}
        {attachOpen ? (
          <View style={styles.suggest}>
            <Chip label="📷  Camera" onPress={() => pickPhoto(true)} />
            <Chip label="🖼  Photo" onPress={() => pickPhoto(false)} />
            <Chip label="📄  PDF or text file" onPress={pickFile} />
          </View>
        ) : null}
        <View style={[styles.composer, { borderTopColor: t.line, backgroundColor: t.card }]}>
          <Pressable accessibilityLabel="Attach a photo or file" onPress={() => setAttachOpen(o => !o)} style={[styles.icon, { borderColor: t.line }]}>
            <Ionicons name={attachOpen ? 'close' : 'attach'} size={22} color={t.text} />
          </Pressable>
          {rec.isRecording ? (
            <View style={[styles.input, styles.recording, { borderColor: t.rose }]}>
              <View style={[styles.dot, { backgroundColor: t.rose }]} />
              <Text style={{ color: t.text }}>Recording {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')}. Tap stop to send.</Text>
            </View>
          ) : (
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder="Message your assistant"
              placeholderTextColor={t.muted}
              multiline
              style={[styles.input, { color: t.text, borderColor: t.line, backgroundColor: t.bg }]}
              accessibilityLabel="Message"
            />
          )}
          {text.trim() && !rec.isRecording ? (
            <Pressable accessibilityLabel="Send" onPress={() => send()} disabled={!!busy} style={[styles.icon, { backgroundColor: t.ink, borderColor: t.ink, opacity: busy ? 0.5 : 1 }]}>
              <Ionicons name="arrow-up" size={22} color="#fff" />
            </Pressable>
          ) : (
            <Pressable
              accessibilityLabel={rec.isRecording ? 'Stop and send voice note' : 'Record a voice note'}
              onPress={toggleRecording}
              disabled={!!busy}
              style={[styles.icon, { backgroundColor: rec.isRecording ? t.rose : t.ink, borderColor: rec.isRecording ? t.rose : t.ink }]}>
              <Ionicons name={rec.isRecording ? 'stop' : 'mic'} size={22} color="#fff" />
            </Pressable>
          )}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: space.m, paddingHorizontal: space.l, paddingVertical: space.m, borderBottomWidth: 1 },
  avatar: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#2B1C02', fontWeight: '700', fontSize: 17 },
  thread: { padding: space.l, gap: space.s, flexGrow: 1, maxWidth: 760, width: '100%', alignSelf: 'center' },
  bubble: { maxWidth: '86%', paddingVertical: 9, paddingHorizontal: 13, borderRadius: 18 },
  me: { alignSelf: 'flex-end', borderBottomRightRadius: 4 },
  them: { alignSelf: 'flex-start', borderWidth: 1, borderBottomLeftRadius: 4 },
  meta: { fontSize: 11, marginTop: 3 },
  suggest: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s, paddingHorizontal: space.l, paddingBottom: space.s },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: space.s, padding: space.s, borderTopWidth: 1 },
  icon: { width: 44, height: 44, borderRadius: 22, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  input: { flex: 1, minHeight: 44, maxHeight: 140, borderWidth: 1, borderRadius: radius.l, paddingHorizontal: 14, paddingTop: 11, paddingBottom: 11, fontSize: 16 },
  recording: { flexDirection: 'row', alignItems: 'center', gap: space.s },
  dot: { width: 10, height: 10, borderRadius: 5 },
});
