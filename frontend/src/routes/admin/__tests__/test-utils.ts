import { vi, type Mock } from 'vitest';

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
