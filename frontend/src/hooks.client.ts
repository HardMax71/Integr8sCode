import type { ClientInit, HandleClientError } from '@sveltejs/kit/hooks';
import { configureSync, getConsoleSink, getLogger } from '@logtape/logtape';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';

const log = getLogger(['integr8scode', 'app']);

export const init: ClientInit = () => {
    configureSync({
        sinks: { console: getConsoleSink() },
        loggers: [
            { category: 'integr8scode', lowestLevel: import.meta.env.DEV ? 'debug' : 'warning', sinks: ['console'] },
            // LogTape reports its own failures here; at warning it skips its startup notice
            { category: ['logtape', 'meta'], lowestLevel: 'warning', sinks: ['console'] },
        ],
    });
    initializeApiInterceptors();
};

export const handleError: HandleClientError = ({ kind, error, event }) => {
    log.error('Unexpected {kind} error on {path}: {error}', { kind, path: event.url.pathname, error });
};
