import { requireOptionalNativeModule, type EventSubscription } from 'expo';
import { Platform } from 'react-native';

/** Events the Android phone agent sends while it works. */
export type AgentEvent =
  | { type: 'service'; enabled: boolean }
  | { type: 'started' | 'resumed' | 'stopped'; jobId: number }
  | { type: 'step'; jobId: number; action: string; progress: string }
  | { type: 'need_user'; jobId: number; reason: string; message: string }
  | { type: 'done' | 'stop' | 'error'; jobId: number; message: string };

export type AgentState = { running: boolean; jobId: number | null; goal: string | null; waitingFor: string | null; message: string };

type NativePhoneAgent = {
  isEnabled(): boolean;
  openSettings(): boolean;
  start(jobId: number, goal: string, apiUrl: string, token: string): boolean;
  resume(): boolean;
  stop(): boolean;
  getState(): AgentState;
  addListener(event: 'onAgentEvent', listener: (e: AgentEvent) => void): EventSubscription;
};

// Only present in Android builds made with EAS or `expo run:android` (not in Expo Go, iOS or the web).
const native = Platform.OS === 'android' ? requireOptionalNativeModule<NativePhoneAgent>('PhoneAgent') : null;

export const phoneAgentAvailable = !!native;

export const PhoneAgent = {
  isEnabled: () => native?.isEnabled() ?? false,
  openSettings: () => native?.openSettings() ?? false,
  start: (jobId: number, goal: string, apiUrl: string, token: string) => native?.start(jobId, goal, apiUrl, token) ?? false,
  resume: () => native?.resume() ?? false,
  stop: () => native?.stop() ?? false,
  getState: (): AgentState => native?.getState() ?? { running: false, jobId: null, goal: null, waitingFor: null, message: '' },
  addListener: (fn: (e: AgentEvent) => void): EventSubscription | null => native?.addListener('onAgentEvent', fn) ?? null,
};
