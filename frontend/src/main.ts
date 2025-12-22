import { client } from './lib/api/client.gen';
import { mount } from 'svelte';
import App from './App.svelte';
import ErrorDisplay from './components/ErrorDisplay.svelte';
import { appError } from './stores/errorStore';
import './app.css';

// Configure the API client with credentials
// Note: SDK already has full paths like '/api/v1/auth/login', so baseUrl should be empty
client.setConfig({
  baseUrl: '',
  credentials: 'include',
});

// Global error handlers to catch unhandled errors
window.onerror = (message, source, lineno, colno, error) => {
  console.error('[Global Error]', { message, source, lineno, colno, error });
  appError.setError(error || String(message), 'Unexpected Error');
  return true; // Prevent default browser error handling
};

window.onunhandledrejection = (event) => {
  console.error('[Unhandled Promise Rejection]', event.reason);
  appError.setError(event.reason, 'Unhandled Promise Error');
  event.preventDefault(); // Prevent default handling to match onerror behavior
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
