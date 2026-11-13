import { View } from 'react-native';

import { Text } from '@/components/text';
import { useTheme } from '@/lib/theme';

/** The wordmark: lowercase "aide" with the saffron dot. */
export function Wordmark({ size = 34 }: { size?: number }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-end' }} accessibilityRole="header" accessibilityLabel="Aide">
      <Text style={{ fontSize: size, lineHeight: size * 1.1, fontWeight: '700', letterSpacing: -size * 0.05, color: t.text }}>aide</Text>
      <View style={{ width: size * 0.22, height: size * 0.22, borderRadius: size, backgroundColor: t.marigold, marginLeft: 2, marginBottom: size * 0.16 }} />
    </View>
  );
}
