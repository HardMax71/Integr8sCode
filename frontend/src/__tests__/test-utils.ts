/**
 * Shared test utilities for Vitest tests.
 *
 * Note: createMockStore must be defined inside vi.hoisted() in each test file
 * because vi.hoisted() runs before imports and cannot access external modules.
 * This is a Vitest limitation, not a design choice.
 */

import { vi, type Mock } from 'vitest';
import userEvent from '@testing-library/user-event';
import { EVENT_TYPES } from '$lib/admin/events/eventTypes';
import type {
  ExecutionCompletedEvent,
  EventBrowseResponse,
  EventDetailResponse,
  EventStatsResponse,
  AdminUserOverview,
  NotificationResponse,
  EventMetadata,
  EventType,
} from '$lib/api';

export type UserEventInstance = ReturnType<typeof userEvent.setup>;

export const user: UserEventInstance = userEvent.setup({
  delay: null,
  pointerEventsCheck: 0,
});

// ============================================================================
// Mock Store Type (for use with vi.hoisted)
// ============================================================================

/**
 * Type definition for mock stores created with createMockStore.
 * Use this for type annotations in test files.
 */
export interface MockStore<T> {
  set(v: T): void;
  subscribe(fn: (v: T) => void): () => void;
  update(fn: (v: T) => T): void;
  _getValue?(): T;
}

/**
 * Type definition for mock derived stores.
 */
export interface MockDerivedStore<T> {
  subscribe(fn: (v: T) => void): () => void;
}

// ============================================================================
// Console Suppression Utilities
// ============================================================================

/**
 * Suppresses console.error for the duration of a test.
 * Returns a function to restore the original behavior.
 */
export function suppressConsoleError(): () => void {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  return () => spy.mockRestore();
}

/**
 * Suppresses console.warn for the duration of a test.
 * Returns a function to restore the original behavior.
 */
export function suppressConsoleWarn(): () => void {
  const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  return () => spy.mockRestore();
}

// ============================================================================
// Mock Module Factories (for use with async vi.mock() factories)
// ============================================================================

/**
 * Creates a mock module with named Svelte 5 component exports.
 * Each component has proper $$ structure for Svelte 5 compatibility.
 *
 * @param components - Record mapping export names to HTML strings
 */
export function createMockNamedComponents(components: Record<string, string>): Record<string, unknown> {
  const module: Record<string, unknown> = {};
  for (const [name, html] of Object.entries(components)) {
    const Mock = function () {
      return {};
    } as unknown as { new (): object; render: () => { html: string; css: { code: string; map: null }; head: string } };
    Mock.render = () => ({ html, css: { code: '', map: null }, head: '' });
    module[name] = Mock;
  }
  return module;
}

// ============================================================================
// Test Data Factories
// ============================================================================

/**
 * Creates a mock notification for testing.
 */
export function createMockNotification(overrides: Partial<NotificationResponse> = {}): NotificationResponse {
  return {
    notification_id: 'notif-1',
    subject: 'Test Notification',
    body: 'This is a test notification body',
    channel: 'in_app',
    status: 'delivered',
    severity: 'medium',
    tags: [],
    created_at: new Date().toISOString(),
    action_url: '',
    read_at: null,
    ...overrides,
  };
}

/**
 * Creates multiple mock notifications for testing.
 */
export function createMockNotifications(count: number): NotificationResponse[] {
  return Array.from({ length: count }, (_, i) =>
    createMockNotification({
      notification_id: `notif-${i + 1}`,
      subject: `Notification ${i + 1}`,
      body: `Body for notification ${i + 1}`,
      status: i % 2 === 0 ? 'delivered' : 'read',
    })
  );
}

// ============================================================================
// Admin Event Mock Helpers
// ============================================================================

export function mockWindowGlobals(openMock: Mock, confirmMock: Mock): void {
  vi.stubGlobal('open', openMock);
  vi.stubGlobal('confirm', confirmMock);
}

export type MockEventOverrides = Omit<Partial<ExecutionCompletedEvent>, 'event_type' | 'metadata'> & {
  event_type?: EventType;
  metadata?: Partial<EventMetadata>;
};

export const DEFAULT_EVENT: ExecutionCompletedEvent = {
  event_id: 'evt-1',
  event_type: 'execution_completed',
  event_version: '1',
  timestamp: '2024-01-15T10:30:00Z',
  aggregate_id: 'exec-456',
  metadata: {
    service_name: 'test-service',
    service_version: '1.0.0',
    user_id: 'user-1',
  },
  execution_id: 'exec-456',
  exit_code: 0,
  stdout: 'hello',
};

export { EVENT_TYPES };

export const createMockEvent = (overrides: MockEventOverrides = {}): ExecutionCompletedEvent => {
  const { metadata: metadataOverrides, ...rest } = overrides;
  return {
    ...DEFAULT_EVENT,
    ...rest,
    metadata: { ...DEFAULT_EVENT.metadata, ...metadataOverrides },
  } as ExecutionCompletedEvent;
};

export const createMockEvents = (count: number): EventBrowseResponse['events'] =>
  Array.from({ length: count }, (_, i) => ({
    ...createMockEvent({
      event_id: `evt-${i + 1}`,
      aggregate_id: `exec-${i + 1}`,
      metadata: {
        user_id: `user-${(i % 3) + 1}`,
        service_name: 'execution-service',
      },
    }),
    event_type: EVENT_TYPES[i % EVENT_TYPES.length],
    timestamp: new Date(Date.now() - i * 60000).toISOString(),
  } as EventBrowseResponse['events'][number]));

export function createMockStats(overrides: Partial<EventStatsResponse> = {}): EventStatsResponse {
  return {
    total_events: 150,
    error_rate: 2.5,
    avg_processing_time: 1.23,
    top_users: [{ user_id: 'user-1', event_count: 50 }],
    events_by_type: [],
    events_by_hour: [],
    ...overrides,
  };
}

export function createMockEventDetail(event = createMockEvent()): EventDetailResponse {
  return {
    event: event as EventDetailResponse['event'],
    related_events: [
      { event_id: 'rel-1', event_type: 'execution_started', timestamp: '2024-01-15T10:29:00Z' },
      { event_id: 'rel-2', event_type: 'pod_created', timestamp: '2024-01-15T10:29:30Z' },
    ],
    timeline: [],
  };
}

export function createMockUserOverview(): AdminUserOverview {
  return {
    user: {
      user_id: 'user-1',
      username: 'testuser',
      email: 'test@example.com',
      role: 'user',
      is_active: true,
      is_superuser: false,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      bypass_rate_limit: null,
      global_multiplier: null,
      has_custom_limits: null,
    },
    stats: {
      total_events: 100,
      events_by_type: [],
      events_by_service: [],
      events_by_hour: [],
      top_users: [],
      error_rate: 0,
      avg_processing_time: 0,
      start_time: null,
      end_time: null,
    },
    derived_counts: { succeeded: 80, failed: 10, timeout: 5, cancelled: 5, terminal_total: 100 },
    rate_limit_summary: { bypass_rate_limit: false, global_multiplier: 1, has_custom_limits: false },
    recent_events: [createMockEvent() as AdminUserOverview['recent_events'][number]],
  };
}
