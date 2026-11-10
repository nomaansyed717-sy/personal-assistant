import { useColorScheme } from 'react-native';

// Same palette as the web app: deep teal ink, marigold for the one loud thing (approvals).
const light = {
  ink: '#0E3B43',
  ink2: '#165A66',
  bg: '#EEF3F2',
  card: '#FFFFFF',
  text: '#15282C',
  muted: '#5B7177',
  line: '#D5E0DE',
  marigold: '#E8A33D',
  marigoldSoft: '#FBEFD9',
  leaf: '#2F8F6B',
  rose: '#B4483C',
  onInk: '#FFFFFF',
  bubbleMe: '#0E3B43',
  bubbleMeText: '#FFFFFF',
};

const dark: typeof light = {
  ink: '#0E3B43',
  ink2: '#2A7A87',
  bg: '#0C1A1D',
  card: '#132529',
  text: '#E3ECEA',
  muted: '#9AB0B4',
  line: '#24393E',
  marigold: '#E8A33D',
  marigoldSoft: '#3A2D16',
  leaf: '#46B38A',
  rose: '#D9695C',
  onInk: '#FFFFFF',
  bubbleMe: '#1F6B77',
  bubbleMeText: '#FFFFFF',
};

export type Palette = typeof light;

export function useTheme(): Palette {
  return useColorScheme() === 'dark' ? dark : light;
}

export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24, xxl: 32 };
export const radius = { s: 8, m: 12, l: 18, pill: 999 };
