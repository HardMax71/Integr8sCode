import { mount } from 'svelte';
import App from './App.svelte';
import ErrorDisplay from '$components/ErrorDisplay.svelte';
import { appError } from '$stores/errorStore.svelte';
import { initializeApiInterceptors } from '$lib/api-interceptors';
import { logger } from '$lib/logger';
import './app.css';

const log = logger.withTag('Global');

initializeApiInterceptors();

// Global error handlers to catch unhandled errors
window.onerror = (message, source, lineno, colno, error) => {
  log.error('[Global Error]', { message, source, lineno, colno, error });
  appError.setError(error ?? new Error(typeof message === 'string' ? message : 'Unknown error'), 'Unexpected Error');
  return true; // Prevent default browser error handling
};

window.onunhandledrejection = (event) => {
  log.error('[Unhandled Promise Rejection]', event.reason);
  const error = event.reason instanceof Error ? event.reason : new Error(String(event.reason));
  appError.setError(error, 'Unexpected Error');
  event.preventDefault();
};

// Mount the app with error handling
let app;
try {
  app = mount(App, {
    target: document.body,
  });
} catch (error) {
  log.error('[Mount Error]', error);
  // If App fails to mount, show error display directly
  app = mount(ErrorDisplay, {
    target: document.body,
    props: {
      error: error instanceof Error ? error : new Error(String(error)),
      title: 'Failed to Load Application'
    }
  });
}

export default app;
