import { PhoneAgent, phoneAgentAvailable } from '../../modules/phone-agent';
import { API_URL, api } from './api';

export type PhoneJob = {
  id: number;
  goal: string;
  app_hint: string | null;
  status: 'queued' | 'running' | 'waiting_user' | 'done' | 'failed' | 'stopped';
  waiting_for: string | null;
  message: string | null;
  result: string | null;
  step_count: number;
  created_at: string | null;
  updated_at: string | null;
  steps?: { n: number; action: string; note: string; package?: string; typed?: string }[];
};

export { PhoneAgent, phoneAgentAvailable };

/**
 * Start the oldest queued task (one the user typed, or a phone task they approved in chat) on this phone.
 * Returns the job that started, or null when nothing is queued, the agent is off, or one is already running.
 */
export async function startQueued(token: string | null): Promise<PhoneJob | null> {
  if (!token || !phoneAgentAvailable || !PhoneAgent.isEnabled() || PhoneAgent.getState().running) return null;
  const job = await api<PhoneJob | null>('/phone/jobs/next');
  if (!job) return null;
  return PhoneAgent.start(job.id, job.goal, API_URL, token) ? job : null;
}

export const STATUS_LABEL: Record<PhoneJob['status'], string> = {
  queued: 'Waiting to start',
  running: 'Working',
  waiting_user: 'Your turn',
  done: 'Done',
  failed: 'Stopped',
  stopped: 'Stopped by you',
};
