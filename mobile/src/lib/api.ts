import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/** Where the backend lives. Set EXPO_PUBLIC_API_URL, or "apiUrl" under "extra" in app.json. */
export const API_URL: string = (
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ||
  'http://localhost:8000'
).replace(/\/$/, '');

const TOKEN_KEY = 'aide_token';

// SecureStore keeps the token in the Android Keystore. The web build (for development) uses localStorage.
export const tokenStore = {
  async get(): Promise<string | null> {
    if (Platform.OS === 'web') {
      try { return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null; } catch { return null; }
    }
    return SecureStore.getItemAsync(TOKEN_KEY);
  },
  async set(token: string): Promise<void> {
    if (Platform.OS === 'web') {
      try { globalThis.localStorage?.setItem(TOKEN_KEY, token); } catch {}
      return;
    }
    await SecureStore.setItemAsync(TOKEN_KEY, token);
  },
  async clear(): Promise<void> {
    if (Platform.OS === 'web') {
      try { globalThis.localStorage?.removeItem(TOKEN_KEY); } catch {}
      return;
    }
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  },
};

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setSessionToken(t: string | null) {
  token = t;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = { 'X-Requested-With': 'aide', Accept: 'application/json' };
  if (json) h['Content-Type'] = 'application/json';
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

/** The address builds get when no backend URL was set at build time. */
const PLACEHOLDER_HOST = 'your-app.onrender.com';
const host = () => API_URL.replace(/^https?:\/\//, '');

async function handle<T>(r: Response): Promise<T> {
  const isJson = (r.headers.get('content-type') || '').includes('application/json');
  const data = isJson ? await r.json().catch(() => ({})) : {};
  if (r.status === 401 && token) {
    onUnauthorized?.();
  }
  if (!r.ok) {
    if (typeof data?.detail === 'string') throw new ApiError(data.detail, r.status);
    // Not our API answering (a host's "not found" page, a proxy error): say so plainly.
    if (!isJson) throw new ApiError(`Aide's server at ${host()} isn't responding (${r.status}). Try again in a minute.`, r.status);
    throw new ApiError('Something went wrong. Please try again.', r.status);
  }
  return data as T;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  if (API_URL.includes(PLACEHOLDER_HOST)) {
    throw new ApiError('This build isn’t connected to a server yet. Set AIDE_API_URL and rebuild the app.', 0);
  }
  let r: Response;
  try {
    r = await fetch(API_URL + '/api' + path, {
      method: opts.method || 'GET',
      headers: headers(),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(`Can’t reach Aide’s server at ${host()}. Check your internet connection and try again.`, 0);
  }
  return handle<T>(r);
}

export type UploadFile = { uri: string; name: string; type: string };

/** Send a photo, PDF, text file or voice note to the chat. */
export async function upload(file: UploadFile, opts: { caption?: string; voice?: boolean } = {}) {
  const fd = new FormData();
  if (Platform.OS === 'web') {
    const blob = await (await fetch(file.uri)).blob();
    fd.append('file', blob, file.name);
  } else {
    // React Native's FormData takes a {uri, name, type} object for files.
    fd.append('file', file as unknown as Blob);
  }
  if (opts.caption) fd.append('caption', opts.caption);
  fd.append('voice', opts.voice ? 'true' : 'false');
  let r: Response;
  try {
    r = await fetch(API_URL + '/api/chat/upload', { method: 'POST', headers: headers(false), body: fd });
  } catch {
    throw new ApiError(`Can’t reach Aide’s server at ${host()}. Check your internet connection and try again.`, 0);
  }
  return handle<{ reply: string; transcript: string | null }>(r);
}

// ---- shapes returned by the API

export type Me = {
  name: string | null;
  assistant_name: string;
  persona: string | null;
  timezone: string;
  brief_hour: number;
  ideas_enabled: boolean;
  training_opt_in: boolean;
  paused: boolean;
  onboarding_state: 'new' | 'awaiting_consent' | 'awaiting_connect' | 'syncing' | 'active';
  demo: boolean;
  phone: string | null;
  email: string | null;
  channel: string;
  push_previews: boolean;
  voice_language: string;
  telegram?: { available: boolean; linked: boolean; username: string | null; notify: boolean };
  google: string | null;
};

export type ChatMessage = { id: number; from: 'me' | 'assistant'; channel: string; text: string; at: string };

export type Approval = {
  id: number;
  number: number;
  kind: string;
  tier: number;
  preview: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Today = {
  greeting: string;
  assistant_name: string;
  events: { title: string; start: string; end: string | null }[];
  loops: { id: number; direction: 'user_owes' | 'owed_to_user'; description: string; person: string | null; due_at: string | null }[];
  approvals: number;
  goals: { id: number; title: string; progress_note: string | null }[];
  standing_tasks: number;
  subscriptions_monthly: Record<string, number>;
  paused: boolean;
};

export type Goal = { id: number; title: string; detail: string | null; status: string; progress_note: string | null; target_date: string | null };
export type StandingTask = {
  id: number; title: string; instruction: string; schedule: string; status: string;
  next_run_at: string | null; last_result: string | null; runs: number;
};
export type Memory = { id: number; text: string };
export type Skill = { name: string; description: string; builtin: boolean; id?: number };
export type Subscription = { id: number; merchant: string; amount: number | null; currency: string | null; cadence: string | null; status: string };
export type VaultItem = { id: number; label: string; site: string; username?: string };
export type Activity = {
  planned: { when: string; what: string }[];
  done: { at: string; actor: string; action: string; label: string; detail: string }[];
};

export type CatalogApp = { id: string; name: string; auth: 'none' | 'token' | 'oauth'; url: string; help: string; blurb: string };
export type ConnectedApp = {
  id: number; name: string; slug: string; catalog_id: string; auth: 'none' | 'token' | 'oauth';
  status: 'active' | 'needs_auth' | 'error'; last_error: string | null; url_host: string;
  tools: { name: string; read_only: boolean }[]; tool_count: number;
};

export type Automation = {
  id: number; title: string; source: 'email' | 'webhook'; match: { from?: string; subject?: string; text?: string };
  instruction: string; status: 'active' | 'paused'; fires: number; webhook_url: string | null;
  last_fired_at: string | null; last_result: string | null; summary: string;
};
