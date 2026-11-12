import type { ComponentProps } from 'react';
import { StyleSheet, Text as RNText, TextInput as RNTextInput } from 'react-native';

import { fontFor } from '@/lib/theme';

/**
 * Text and TextInput that use Inter everywhere. A fontWeight in the style picks the matching Inter file,
 * so screens can keep writing fontWeight: '600' and get the right face on Android and iOS.
 * (React 19 passes `ref` through as an ordinary prop.)
 */
function interStyle<S>(style: S): S {
  const flat = (StyleSheet.flatten(style as never) || {}) as { fontFamily?: string; fontWeight?: string | number };
  if (flat.fontFamily) return style;
  const { fontWeight, ...rest } = flat;
  return [rest, { fontFamily: fontFor(fontWeight) }] as unknown as S;
}

export function Text({ style, ...props }: ComponentProps<typeof RNText>) {
  return <RNText {...props} style={interStyle(style)} />;
}

export function TextInput({ style, ...props }: ComponentProps<typeof RNTextInput>) {
  return <RNTextInput {...props} style={interStyle(style)} />;
}
