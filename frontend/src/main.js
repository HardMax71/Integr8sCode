import App from './App.svelte';
import './app.css';
import axios from 'axios';

axios.defaults.withCredentials = true;

const app = new App({
  target: document.body,
});

export default app;