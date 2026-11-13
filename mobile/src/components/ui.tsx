import { useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  type RefreshControlProps,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Text, TextInput } from '@/components/text';
import { hairline, radius, space, useTheme } from '@/lib/theme';

export { Text, TextInput };

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
        <ScrollView contentContainerStyle={styles.screen} refreshControl={refreshControl} keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}>
          <View style={styles.column}>{children}</View>
        </ScrollView>
      ) : (
        <View style={{ flex: 1 }}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Title({ children, sub, eyebrow }: { children: ReactNode; sub?: string; eyebrow?: string }) {
  const t = useTheme();
  return (
    <View style={{ marginBottom: space.xl, marginTop: space.s }}>
      {eyebrow ? <Text style={[styles.eyebrow, { color: t.muted }]}>{eyebrow}</Text> : null}
      <Text style={[styles.title, { color: t.text }]}>{children}</Text>
      {sub ? <Text style={{ color: t.muted, marginTop: 8, fontSize: 15, lineHeight: 22 }}>{sub}</Text> : null}
    </View>
  );
}

export function Section({ children, action }: { children: ReactNode; action?: ReactNode }) {
  const t = useTheme();
  return (
    <View style={styles.sectionRow}>
      <Text style={[styles.section, { color: t.muted }]}>{children}</Text>
      {action}
    </View>
  );
}

export function Card({ children, style, accent, flat }: { children: ReactNode; style?: ViewStyle; accent?: boolean; flat?: boolean }) {
  const t = useTheme();
  return (
    <View style={[
      styles.card,
      accent ? { backgroundColor: t.marigoldSoft, borderColor: 'transparent' }
        : flat ? { backgroundColor: t.soft, borderColor: 'transparent' }
          : { backgroundColor: t.card, borderColor: t.line },
      style,
    ]}>
      {children}
    </View>
  );
}

export function P({ children, muted, small, bold, style, numberOfLines }: {
  children: ReactNode; muted?: boolean; small?: boolean; bold?: boolean; style?: TextStyle; numberOfLines?: number;
}) {
  const t = useTheme();
  return (
    <Text numberOfLines={numberOfLines} style={[{ color: muted ? t.muted : t.text, fontSize: small ? 13 : 15.5, lineHeight: small ? 19 : 23, fontWeight: bold ? '600' : '400' }, style]}>
      {children}
    </Text>
  );
}

/** Renders the assistant's *bold* and _italic_ markers. */
export function Rich({ text, color, style }: { text: string; color?: string; style?: TextStyle }) {
  const t = useTheme();
  const parts = String(text).split(/(\*[^*\n]+\*|\b_[^_\n]+_\b)/g);
  return (
    <Text style={[{ color: color || t.text, fontSize: 15.5, lineHeight: 23 }, style]}>
      {parts.map((p, i) =>
        /^\*[^*\n]+\*$/.test(p) ? <Text key={i} style={{ fontWeight: '600', color: color || t.text }}>{p.slice(1, -1)}</Text>
          : /^_[^_\n]+_$/.test(p) ? <Text key={i} style={{ fontStyle: 'italic', color: color || t.text }}>{p.slice(1, -1)}</Text>
            : p,
      )}
    </Text>
  );
}

export function Button({ title, onPress, kind = 'primary', disabled, busy, small, style }: {
  title: string;
  onPress: () => void | Promise<void>;
  kind?: 'primary' | 'ghost' | 'warn' | 'accent' | 'plain';
  disabled?: boolean;
  busy?: boolean;
  small?: boolean;
  style?: ViewStyle;
}) {
  const t = useTheme();
  const [running, setRunning] = useState(false);
  const bg = { primary: t.ink, ghost: t.soft, warn: t.soft, accent: t.marigold, plain: 'transparent' }[kind];
  const fg = { primary: t.onInk, ghost: t.text, warn: t.rose, accent: t.onAccent, plain: t.ink2 }[kind];
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
        { backgroundColor: bg, opacity: off ? 0.4 : pressed ? 0.8 : 1, transform: [{ scale: pressed ? 0.98 : 1 }] },
        style,
      ]}>
      {busy || running ? <ActivityIndicator color={fg} /> : (
        <Text style={{ color: fg, fontWeight: '600', fontSize: small ? 13.5 : 15.5, letterSpacing: -0.1 }}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Field({ label, ...props }: TextInputProps & { label?: string }) {
  const t = useTheme();
  const [focused, setFocused] = useState(false);
  return (
    <View style={{ marginBottom: space.m }}>
      {label ? <Text style={[styles.label, { color: t.muted }]}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={t.muted}
        {...props}
        onFocus={e => { setFocused(true); props.onFocus?.(e); }}
        onBlur={e => { setFocused(false); props.onBlur?.(e); }}
        style={[
          styles.input,
          { color: t.text, backgroundColor: focused ? t.card : t.soft, borderColor: focused ? t.text : 'transparent' },
          props.multiline && { minHeight: 96, textAlignVertical: 'top' },
          props.style,
        ]}
      />
    </View>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  const t = useTheme();
  return (
    <View style={[styles.empty, { backgroundColor: t.soft }]}>
      <Text style={{ color: t.muted, textAlign: 'center', lineHeight: 21, fontSize: 14 }}>{children}</Text>
    </View>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap: space.s }, style]}>{children}</View>;
}

export function Chip({ label, onPress }: { label: string; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chip, { backgroundColor: t.soft, opacity: pressed ? 0.6 : 1 }]}>
      <Text style={{ color: t.text, fontSize: 13.5, flexShrink: 1 }}>{label}</Text>
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
      style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: space.m, gap: space.m }}>
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.text, fontSize: 15, fontWeight: '500' }}>{label}</Text>
        {hint ? <Text style={{ color: t.muted, fontSize: 13, marginTop: 2 }}>{hint}</Text> : null}
      </View>
      <View style={[styles.track, { backgroundColor: value ? t.ink : t.trackOff }]}>
        <View style={[styles.knob, { backgroundColor: value ? t.onInk : t.card, transform: [{ translateX: value ? 18 : 0 }] }]} />
      </View>
    </Pressable>
  );
}

/** A small status pill: neutral, accent (needs you), good or bad. */
export function Pill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'accent' | 'good' | 'bad' }) {
  const t = useTheme();
  const c = { neutral: [t.soft, t.muted], accent: [t.marigoldSoft, t.ink2], good: [t.soft, t.leaf], bad: [t.soft, t.rose] }[tone];
  return (
    <View style={[styles.pill, { backgroundColor: c[0] }]}>
      <Text style={{ color: c[1], fontSize: 11.5, fontWeight: '600', letterSpacing: 0.2 }}>{label}</Text>
    </View>
  );
}

export function Loading() {
  const t = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.bg }}>
      <ActivityIndicator color={t.text} />
    </View>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  const t = useTheme();
  if (!children) return null;
  return <Text style={{ color: t.rose, marginVertical: space.s, fontSize: 14 }} accessibilityLiveRegion="polite">{children}</Text>;
}

export const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

export const money = (n: number, cur: string) => {
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n); }
  catch { return `${cur} ${Math.round(n)}`; }
};

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 20, paddingTop: space.l, paddingBottom: space.xxl * 2 },
  column: { width: '100%', maxWidth: 680, alignSelf: 'center' },
  eyebrow: { fontSize: 13, fontWeight: '500', marginBottom: 6 },
  title: { fontSize: 32, lineHeight: 38, fontWeight: '700', letterSpacing: -1 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 28, marginBottom: 10 },
  section: { fontSize: 12, fontWeight: '600', letterSpacing: 0.9, textTransform: 'uppercase' },
  card: { borderWidth: hairline, borderRadius: radius.l, padding: 18, marginBottom: 10 },
  button: { borderRadius: radius.pill, height: 50, paddingHorizontal: 22, alignItems: 'center', justifyContent: 'center' },
  buttonSmall: { height: 36, paddingHorizontal: 14 },
  label: { fontWeight: '500', fontSize: 13, marginBottom: 6 },
  input: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 13, fontSize: 16 },
  empty: { borderRadius: radius.l, paddingVertical: 28, paddingHorizontal: 20 },
  chip: { borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14, maxWidth: '100%' },
  track: { width: 44, height: 26, borderRadius: 13, padding: 3 },
  knob: { width: 20, height: 20, borderRadius: 10 },
  pill: { borderRadius: radius.pill, paddingVertical: 3, paddingHorizontal: 9, alignSelf: 'flex-start' },
});
