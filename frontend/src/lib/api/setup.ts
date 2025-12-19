import { client } from './client.gen';
import { get } from 'svelte/store';
import { csrfToken } from '../../stores/auth';

client.setConfig({
    baseUrl: '',
    credentials: 'include',
});

client.interceptors.request.use((request) => {
    const token = get(csrfToken);
    if (token && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(request.method?.toUpperCase() ?? '')) {
        request.headers.set('X-CSRF-Token', token);
    }
    return request;
});
