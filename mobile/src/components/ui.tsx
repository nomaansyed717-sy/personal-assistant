import { useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
  type RefreshControlProps,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { radius, space, useTheme } from '@/lib/theme';

/** Scrollable screen with the app background and safe-area padding. */
export function Screen({ children, refreshControl, edges = ['top'] as ('top' | 'bottom')[], scroll = true }: {
  children: ReactNode;
  refreshControl?: React.ReactElement<RefreshControlProps>;
  edges?: ('top' | 'bottom')[];
  scroll?: boolean;
}) {
  const t = useTheme();
  return (
    <SafeAreaView edges={edges} style={{ flex: 1, backgroundColor: t.bg }}>
      {scroll ? (
        <ScrollView contentContainerStyle={styles.screen} refreshControl={refreshControl} keyboardShouldPersistTaps="handled">
          <View style={styles.column}>{children}</View>
        </ScrollView>
      ) : (
        <View style={{ flex: 1 }}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Title({ children, sub }: { children: ReactNode; sub?: string }) {
  const t = useTheme();
  return (
    <View style={{ marginBottom: space.l }}>
      <Text style={[styles.title, { color: t.text }]}>{children}</Text>
      {sub ? <Text style={{ color: t.muted, marginTop: 4, fontSize: 15, lineHeight: 21 }}>{sub}</Text> : null}
    </View>
  );
}

export function Section({ children }: { children: ReactNode }) {
  const t = useTheme();
  return <Text style={[styles.section, { color: t.text }]}>{children}</Text>;
}

export function Card({ children, style, accent }: { children: ReactNode; style?: ViewStyle; accent?: boolean }) {
  const t = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: accent ? t.marigoldSoft : t.card, borderColor: accent ? t.marigold : t.line }, style]}>
      {children}
    </View>
  );
}

export function P({ children, muted, small, bold, style }: { children: ReactNode; muted?: boolean; small?: boolean; bold?: boolean; style?: TextStyle }) {
  const t = useTheme();
  return (
    <Text style={[{ color: muted ? t.muted : t.text, fontSize: small ? 13 : 16, lineHeight: small ? 18 : 22, fontWeight: bold ? '600' : '400' }, style]}>
      {children}
    </Text>
  );
}

/** Renders the assistant's *bold* and _italic_ markers. */
export function Rich({ text, color, style }: { text: string; color?: string; style?: TextStyle }) {
  const t = useTheme();
  const parts = String(text).split(/(\*[^*\n]+\*|\b_[^_\n]+_\b)/g);
  return (
    <Text style={[{ color: color || t.text, fontSize: 16, lineHeight: 22 }, style]}>
      {parts.map((p, i) =>
        /^\*[^*\n]+\*$/.test(p) ? <Text key={i} style={{ fontWeight: '700' }}>{p.slice(1, -1)}</Text>
          : /^_[^_\n]+_$/.test(p) ? <Text key={i} style={{ fontStyle: 'italic' }}>{p.slice(1, -1)}</Text>
            : p,
      )}
    </Text>
  );
}

export function Button({ title, onPress, kind = 'primary', disabled, busy, small, style }: {
  title: string;
  onPress: () => void | Promise<void>;
  kind?: 'primary' | 'ghost' | 'warn' | 'accent';
  disabled?: boolean;
  busy?: boolean;
  small?: boolean;
  style?: ViewStyle;
}) {
  const t = useTheme();
  const [running, setRunning] = useState(false);
  const bg = { primary: t.ink, ghost: 'transparent', warn: t.rose, accent: t.marigold }[kind];
  const fg = { primary: t.onInk, ghost: t.text, warn: '#fff', accent: '#2B1C02' }[kind];
  const off = disabled || busy || running;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off }}
      disabled={off}
      onPress={async () => {
        setRunning(true);
        try { await onPress(); } finally { setRunning(false); }
      }}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: bg, borderColor: kind === 'ghost' ? t.line : bg, opacity: off ? 0.55 : pressed ? 0.85 : 1 },
        style,
      ]}>
      {busy || running ? <ActivityIndicator color={fg} /> : <Text style={{ color: fg, fontWeight: '600', fontSize: small ? 14 : 16 }}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, ...props }: TextInputProps & { label?: string }) {
  const t = useTheme();
  return (
    <View style={{ marginBottom: space.m }}>
      {label ? <Text style={[styles.label, { color: t.text }]}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={t.muted}
        {...props}
        style={[styles.input, { color: t.text, backgroundColor: t.card, borderColor: t.line }, props.multiline && { minHeight: 90, textAlignVertical: 'top' }, props.style]}
      />
    </View>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  const t = useTheme();
  return (
    <View style={[styles.empty, { borderColor: t.line }]}>
      <Text style={{ color: t.muted, textAlign: 'center', lineHeight: 21 }}>{children}</Text>
    </View>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap: space.s }, style]}>{children}</View>;
}

export function Chip({ label, onPress }: { label: string; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chip, { borderColor: t.line, backgroundColor: t.card, opacity: pressed ? 0.7 : 1 }]}>
      <Text style={{ color: t.text, fontSize: 14, flexShrink: 1 }}>{label}</Text>
    </Pressable>
  );
}

export function Toggle({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string }) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      onPress={() => onChange(!value)}
      style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: space.s, gap: space.m }}>
      <View style={[styles.track, { backgroundColor: value ? t.leaf : t.line }]}>
        <View style={[styles.knob, { transform: [{ translateX: value ? 18 : 0 }] }]} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.text, fontSize: 15, fontWeight: '500' }}>{label}</Text>
        {hint ? <Text style={{ color: t.muted, fontSize: 13 }}>{hint}</Text> : null}
      </View>
    </Pressable>
  );
}

export function Loading() {
  const t = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.bg }}>
      <ActivityIndicator color={t.marigold} size="large" />
    </View>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  const t = useTheme();
  if (!children) return null;
  return <Text style={{ color: t.rose, marginVertical: space.s }} accessibilityLiveRegion="polite">{children}</Text>;
}

export const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

export const money = (n: number, cur: string) => {
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n); }
  catch { return `${cur} ${Math.round(n)}`; }
};

const styles = StyleSheet.create({
  screen: { padding: space.l, paddingBottom: space.xxl * 2 },
  column: { width: '100%', maxWidth: 720, alignSelf: 'center' },
  title: { fontSize: 28, fontWeight: '700', letterSpacing: -0.3 },
  section: { fontSize: 17, fontWeight: '700', marginTop: space.xl, marginBottom: space.s },
  card: { borderWidth: 1, borderRadius: radius.m, padding: space.l, marginBottom: space.s },
  button: { borderRadius: radius.pill, paddingVertical: 13, paddingHorizontal: 20, alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  buttonSmall: { paddingVertical: 8, paddingHorizontal: 14 },
  label: { fontWeight: '600', fontSize: 14, marginBottom: 6 },
  input: { borderWidth: 1, borderRadius: radius.s, paddingHorizontal: 12, paddingVertical: 11, fontSize: 16 },
  empty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: radius.s, padding: space.xl },
  chip: { borderWidth: 1, borderRadius: radius.l, paddingVertical: 7, paddingHorizontal: 12, maxWidth: '100%' },
  track: { width: 44, height: 26, borderRadius: 13, padding: 3 },
  knob: { width: 20, height: 20, borderRadius: 10, backgroundColor: '#fff' },
});
