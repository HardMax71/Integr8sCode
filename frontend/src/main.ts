import { client } from './lib/api/client.gen';
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

// Configure the API client with base URL and credentials
client.setConfig({
  baseUrl: '/api/v1',
  credentials: 'include',
});

const app = mount(App, {
  target: document.body,
});

export default app;
