import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from './api';

let registeredToken: string | null = null;

// Show notifications even while the app is open (the chat screen refreshes on its own).
if (Platform.OS !== 'web') {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: true,
      shouldSetBadge: true,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

/**
 * Ask for permission and register this phone's Expo push token with the backend.
 * Needs a development or production build (EAS) with an EAS projectId and FCM credentials on Android.
 * Returns null quietly when any of that is missing, so the app still works without push.
 */
export async function registerPush(): Promise<string | null> {
  if (Platform.OS === 'web' || !Device.isDevice) return null;
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Messages and approvals',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 200, 120, 200],
        lightColor: '#E8A33D',
      });
    }
    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return null;
    const projectId = Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId;
    if (!projectId) return null;
    const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    await api('/devices', { method: 'POST', body: { token, platform: Platform.OS === 'ios' ? 'ios' : 'android' } });
    registeredToken = token;
    return token;
  } catch {
    return null;
  }
}

export async function unregisterPush(): Promise<void> {
  if (!registeredToken) return;
  try {
    await api('/devices/remove', { method: 'POST', body: { token: registeredToken } });
  } catch {}
  registeredToken = null;
}
