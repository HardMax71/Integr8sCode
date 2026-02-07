import { mount } from 'svelte';
import App from './App.svelte';
import ErrorDisplay from '$components/ErrorDisplay.svelte';
import { appError } from '$stores/errorStore.svelte';
import { initializeApiInterceptors } from '$lib/api-interceptors';
import './app.css';

initializeApiInterceptors();

// Global error handlers to catch unhandled errors
window.onerror = (message, source, lineno, colno, error) => {
  console.error('[Global Error]', { message, source, lineno, colno, error });
  appError.setError(error || String(message), 'Unexpected Error');
  return true; // Prevent default browser error handling
};

window.onunhandledrejection = (event) => {
  console.error('[Unhandled Promise Rejection]', event.reason);
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
  console.error('[Mount Error]', error);
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
