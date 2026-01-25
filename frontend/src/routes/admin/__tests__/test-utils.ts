import { vi, type Mock } from 'vitest';
import { EVENT_TYPES } from '$lib/admin/events/eventTypes';

const animateMock = {
  onfinish: null,
  cancel: vi.fn(),
  finish: vi.fn(),
  pause: vi.fn(),
  play: vi.fn(),
  reverse: vi.fn(),
  commitStyles: vi.fn(),
  persist: vi.fn(),
  currentTime: 0,
  playbackRate: 1,
  pending: false,
  playState: 'running',
  replaceState: 'active',
  startTime: 0,
  timeline: null,
  id: '',
  effect: null,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(() => true),
  updatePlaybackRate: vi.fn(),
  get finished() { return Promise.resolve(this); },
  get ready() { return Promise.resolve(this); },
  oncancel: null,
  onremove: null,
};

/**
 * Creates a mock for Element.prototype.animate used by Svelte transitions.
 */
export function mockElementAnimate(): void {
  Element.prototype.animate = vi.fn().mockImplementation(() => animateMock);
}

/**
 * Sets up window global mocks for open and confirm.
 */
export function mockWindowGlobals(openMock: Mock, confirmMock: Mock): void {
  vi.stubGlobal('open', openMock);
  vi.stubGlobal('confirm', confirmMock);
}

// ============================================================================
// Event Mock Helpers
// ============================================================================

export interface MockEventMetadata {
  service_name: string;
  service_version: string;
  correlation_id?: string;
  user_id?: string | null;
}

export interface MockEventOverrides {
  event_id?: string;
  event_type?: string;
  timestamp?: string;
  aggregate_id?: string;
  metadata?: Partial<MockEventMetadata>;
  // Event-specific payload fields
  execution_id?: string;
  exit_code?: number;
  output?: string;
}

export const DEFAULT_EVENT = {
  event_id: 'evt-1',
  event_type: 'execution_completed',
  timestamp: '2024-01-15T10:30:00Z',
  aggregate_id: 'exec-456',
  metadata: {
    service_name: 'test-service',
    service_version: '1.0.0',
    correlation_id: 'corr-123',
    user_id: 'user-1',
  },
  execution_id: 'exec-456',
  exit_code: 0,
  output: 'hello',
};

/** Re-export EVENT_TYPES from the source for test consistency */
export { EVENT_TYPES } from '$lib/admin/events/eventTypes';

export const createMockEvent = (overrides: MockEventOverrides = {}) => {
  const { metadata: metadataOverrides, ...rest } = overrides;
  return {
    ...DEFAULT_EVENT,
    ...rest,
    metadata: { ...DEFAULT_EVENT.metadata, ...metadataOverrides },
  };
};

export const createMockEvents = (count: number) =>
  Array.from({ length: count }, (_, i) => createMockEvent({
    event_id: `evt-${i + 1}`,
    event_type: EVENT_TYPES[i % EVENT_TYPES.length],
    timestamp: new Date(Date.now() - i * 60000).toISOString(),
    aggregate_id: `exec-${i + 1}`,
    metadata: {
      correlation_id: `corr-${i + 1}`,
      user_id: `user-${(i % 3) + 1}`,
      service_name: 'execution-service',
    },
  }));

export function createMockStats(overrides: Partial<{
  total_events: number;
  error_rate: number;
  avg_processing_time: number;
  top_users: Array<{ user_id: string; count: number }>;
}> = {}) {
  return {
    total_events: 150,
    error_rate: 2.5,
    avg_processing_time: 1.23,
    top_users: [{ user_id: 'user-1', count: 50 }],
    ...overrides,
  };
}

export function createMockEventDetail(event = createMockEvent()) {
  return {
    event,
    related_events: [
      { event_id: 'rel-1', event_type: 'execution_started', timestamp: '2024-01-15T10:29:00Z' },
      { event_id: 'rel-2', event_type: 'pod_created', timestamp: '2024-01-15T10:29:30Z' },
    ],
  };
}

export function createMockUserOverview() {
  return {
    user: {
      user_id: 'user-1',
      username: 'testuser',
      email: 'test@example.com',
      role: 'user',
      is_active: true,
      is_superuser: false,
    },
    stats: { total_events: 100 },
    derived_counts: { succeeded: 80, failed: 10, timeout: 5, cancelled: 5, terminal_total: 100 },
    rate_limit_summary: { bypass_rate_limit: false, global_multiplier: 1, has_custom_limits: false },
    recent_events: [createMockEvent()],
  };
}
