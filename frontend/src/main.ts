import { client } from './lib/api/client.gen';
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

// Configure the API client with credentials
// Note: SDK already has full paths like '/api/v1/auth/login', so baseUrl should be empty
client.setConfig({
  baseUrl: '',
  credentials: 'include',
});

const app = mount(App, {
  target: document.body,
});

export default app;
