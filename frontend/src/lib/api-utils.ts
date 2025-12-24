import { addToast } from '../stores/toastStore';
import type { ValidationError, HttpValidationError } from './api';

type ApiError = { status?: number; detail?: ValidationError[] | string; message?: string };

export function getErrorMessage(err: unknown, fallback = 'Unknown error'): string {
  if (!err) return fallback;
  if (typeof err === 'object' && 'detail' in err) {
    const detail = (err as ApiError).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`).join(', ');
    }
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export function handleApiError(err: unknown, action: string): void {
  console.error(`Failed to ${action}:`, err);
  addToast(`Failed to ${action}: ${getErrorMessage(err)}`, 'error');
}

export function handleValidationError(err: unknown, defaultMsg: string): void {
  const apiErr = err as ApiError | null;
  if (apiErr?.status === 422 && Array.isArray(apiErr.detail)) {
    const msgs = apiErr.detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`);
    addToast(`Validation failed:\n${msgs.join('\n')}`, 'error');
    return;
  }
  addToast(`${defaultMsg}: ${getErrorMessage(err)}`, 'error');
}
