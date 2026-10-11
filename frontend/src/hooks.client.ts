import type { ClientInit, HandleClientError } from '@sveltejs/kit/hooks';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('Global');

export const init: ClientInit = () => {
    initializeApiInterceptors();
};

export const handleError: HandleClientError = ({ kind, error, event }) => {
    log.error('Unexpected error', { kind, path: event.url.pathname, error });
};
