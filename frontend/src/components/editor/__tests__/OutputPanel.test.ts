import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import type { ExecutionResult } from '$lib/api';
import type { ExecutionPhase } from '$lib/editor';

const mocks = vi.hoisted(() => ({
  addToast: vi.fn(),
}));

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule('AlertTriangle', 'FileText', 'Copy'));
vi.mock('svelte-sonner', async () =>
  (await import('$test/test-utils')).createToastMock(mocks.addToast));
vi.mock('$components/Spinner.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<div>Loading...</div>', 'spinner'));

import OutputPanel from '../OutputPanel.svelte';

function makeResult(overrides: Partial<ExecutionResult> = {}): ExecutionResult {
  return {
    execution_id: 'exec-123',
    status: 'completed',
    stdout: null,
    stderr: null,
    lang: 'python',
    lang_version: '3.11',
    resource_usage: null,
    exit_code: 0,
    error_type: null,
    ...overrides,
  };
}

type IdleProps = { phase: ExecutionPhase; result: ExecutionResult | null; error: string | null };

function renderIdle(overrides: Partial<IdleProps> = {}) {
  return render(OutputPanel, {
    props: { phase: 'idle' as ExecutionPhase, result: null, error: null, ...overrides },
  });
}

describe('OutputPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows heading and prompt text when idle with no result or error', () => {
    renderIdle();
    expect(screen.getByText('Execution Output')).toBeInTheDocument();
    expect(screen.getByText(/Write some code and click "Run Script"/)).toBeInTheDocument();
  });

  describe('spinner phases', () => {
    it.each([
      ['starting', 'Starting...'],
      ['queued', 'Queued...'],
      ['scheduled', 'Scheduled...'],
      ['running', 'Running...'],
    ] as const)('phase "%s" shows spinner with label "%s"', (phase, label) => {
      renderIdle({ phase: phase as ExecutionPhase });
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.queryByText(/Write some code/)).not.toBeInTheDocument();
    });
  });

  it('shows error message when error present and no result', () => {
    renderIdle({ error: 'Connection timeout' });
    expect(screen.getByText('Execution Failed')).toBeInTheDocument();
    expect(screen.getByText('Connection timeout')).toBeInTheDocument();
  });

  describe('result rendering', () => {
    it.each([
      ['completed', 'bg-green-50'],
      ['error', 'bg-red-50'],
      ['failed', 'bg-red-50'],
      ['running', 'bg-blue-50'],
      ['queued', 'bg-yellow-50'],
    ] as const)('status "%s" shows badge with %s class', (status, expectedClass) => {
      const { container } = renderIdle({
        result: makeResult({ status: status as ExecutionResult['status'] }),
      });
      expect(screen.getByText(`Status: ${status}`)).toBeInTheDocument();
      expect(container.querySelector(`span.${expectedClass}`)).not.toBeNull();
    });

    it.each([
      { field: 'stdout', heading: 'Output:', content: 'Hello World!' },
      { field: 'stderr', heading: 'Errors:', content: 'NameError: x is not defined' },
    ])('shows $heading when $field present', ({ field, heading, content }) => {
      renderIdle({ result: makeResult({ [field]: content }) });
      expect(screen.getByText(heading)).toBeInTheDocument();
    });

    it('hides stdout and stderr sections when both null', () => {
      renderIdle({ result: makeResult() });
      expect(screen.queryByText('Output:')).not.toBeInTheDocument();
      expect(screen.queryByText('Errors:')).not.toBeInTheDocument();
    });

    it('shows execution ID copy button when execution_id present', () => {
      renderIdle({ result: makeResult({ execution_id: 'abc-123' }) });
      expect(screen.getByLabelText('Click to copy execution ID')).toBeInTheDocument();
    });
  });

  describe('resource usage computations', () => {
    it.each([
      {
        label: 'normal CPU',
        usage: { cpu_time_jiffies: 50, clk_tck_hertz: 100, peak_memory_kb: 10240, execution_time_wall_seconds: 2.345 },
        expectedCpu: '500.000 m',
        expectedMem: '10.000 MiB',
        expectedTime: '2.345 s',
      },
      {
        label: 'zero jiffies shows "< X m"',
        usage: { cpu_time_jiffies: 0, clk_tck_hertz: 100, peak_memory_kb: 2048, execution_time_wall_seconds: 0.5 },
        expectedCpu: '< 10 m',
        expectedMem: '2.000 MiB',
        expectedTime: '0.500 s',
      },
      {
        label: 'missing clk_tck defaults to 100',
        usage: { cpu_time_jiffies: 200, peak_memory_kb: 512, execution_time_wall_seconds: 1 },
        expectedCpu: '2000.000 m',
        expectedMem: '0.500 MiB',
        expectedTime: '1.000 s',
      },
    ])('$label', ({ usage, expectedCpu, expectedMem, expectedTime }) => {
      renderIdle({ result: makeResult({ resource_usage: usage }) });
      expect(screen.getByText('Resource Usage:')).toBeInTheDocument();
      expect(screen.getByText(expectedCpu)).toBeInTheDocument();
      expect(screen.getByText(expectedMem)).toBeInTheDocument();
      expect(screen.getByText(expectedTime)).toBeInTheDocument();
    });

    it('hides resource usage when not present', () => {
      renderIdle({ result: makeResult() });
      expect(screen.queryByText('Resource Usage:')).not.toBeInTheDocument();
    });
  });

  describe('copy to clipboard', () => {
    let writeTextMock: ReturnType<typeof vi.fn>;

    function mockClipboard(resolves = true) {
      writeTextMock = resolves
        ? vi.fn().mockResolvedValue(undefined)
        : vi.fn().mockRejectedValue(new Error('denied'));
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: writeTextMock },
        writable: true,
        configurable: true,
      });
    }

    it.each([
      { target: 'stdout', ariaLabel: 'Copy output to clipboard', text: 'hello world', toastLabel: 'Output' },
      { target: 'stderr', ariaLabel: 'Copy error text to clipboard', text: 'some error', toastLabel: 'Error text' },
      { target: 'execution_id', ariaLabel: 'Click to copy execution ID', text: 'uuid-abc', toastLabel: 'Execution ID' },
    ])('copies $target and shows success toast', async ({ target, ariaLabel, text, toastLabel }) => {
      const user = userEvent.setup();
      mockClipboard();
      renderIdle({
        result: makeResult({ [target]: text }),
      });
      await user.click(screen.getByLabelText(ariaLabel));
      expect(writeTextMock).toHaveBeenCalledWith(text);
      expect(mocks.addToast).toHaveBeenCalledWith('success', `${toastLabel} copied to clipboard`);
    });

    it('shows error toast when clipboard write fails', async () => {
      const user = userEvent.setup();
      mockClipboard(false);
      renderIdle({ result: makeResult({ stdout: 'x' }) });
      await user.click(screen.getByLabelText('Copy output to clipboard'));
      expect(mocks.addToast).toHaveBeenCalledWith('error', 'Failed to copy output');
    });
  });

  describe('render priority', () => {
    it('spinner takes priority over result', () => {
      renderIdle({
        phase: 'running' as ExecutionPhase,
        result: makeResult({ stdout: 'data' }),
      });
      expect(screen.getByText('Running...')).toBeInTheDocument();
      expect(screen.queryByText('Output:')).not.toBeInTheDocument();
    });

    it('result takes priority over error', () => {
      renderIdle({
        result: makeResult({ status: 'error' as ExecutionResult['status'] }),
        error: 'Something went wrong',
      });
      expect(screen.getByText(/Status: error/)).toBeInTheDocument();
      expect(screen.queryByText('Execution Failed')).not.toBeInTheDocument();
    });
  });
});
