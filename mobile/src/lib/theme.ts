import { StyleSheet, useColorScheme } from 'react-native';

/*
 * Aide's look: quiet, warm neutrals, near-black ink, and one saffron accent used sparingly
 * (approvals, the active task, the brand dot). Hairline borders, soft filled surfaces, Inter.
 */
const light = {
  bg: '#F7F7F5',        // app background
  card: '#FFFFFF',      // raised surfaces
  soft: '#EFEFEB',      // filled inputs, chips, secondary buttons
  text: '#0E0F11',
  muted: '#74777B',
  line: '#E7E7E2',
  ink: '#0E0F11',       // primary buttons, my chat bubbles
  onInk: '#FFFFFF',
  ink2: '#C9420B',      // accent for text and icons (readable on light surfaces)
  marigold: '#F05A28',  // accent fill
  marigoldSoft: '#FDEEE7',
  onAccent: '#FFFFFF',
  leaf: '#1E9A69',
  rose: '#D23C3C',
  bubbleMe: '#0E0F11',
  bubbleMeText: '#FFFFFF',
  bubbleThem: '#FFFFFF',
};

const dark: typeof light = {
  bg: '#0B0B0C',
  card: '#151517',
  soft: '#1E1E21',
  text: '#F3F3F1',
  muted: '#8E9196',
  line: '#26262A',
  ink: '#F3F3F1',
  onInk: '#0E0F11',
  ink2: '#FF8752',
  marigold: '#FF6A35',
  marigoldSoft: '#2B1A11',
  onAccent: '#FFFFFF',
  leaf: '#3CC48B',
  rose: '#F06464',
  bubbleMe: '#F3F3F1',
  bubbleMeText: '#0E0F11',
  bubbleThem: '#1A1A1D',
};

export type Palette = typeof light;

export function useTheme(): Palette {
  return useColorScheme() === 'dark' ? dark : light;
}

export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24, xxl: 32 };
export const radius = { s: 10, m: 16, l: 22, pill: 999 };
export const hairline = StyleSheet.hairlineWidth;

/** Inter in four weights. Android picks a custom font by family name, not by fontWeight. */
export const fonts = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
};

export function fontFor(weight?: string | number): string {
  const w = Number(weight === 'bold' ? 700 : weight === 'normal' || weight == null ? 400 : weight);
  if (w >= 700) return fonts.bold;
  if (w >= 600) return fonts.semibold;
  if (w >= 500) return fonts.medium;
  return fonts.regular;
}
