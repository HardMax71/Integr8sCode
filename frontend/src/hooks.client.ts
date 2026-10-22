import type { ClientInit, HandleClientError } from '@sveltejs/kit/hooks';
import { configure, getLogger } from '@logtape/logtape';
import { getOpenTelemetrySink } from '@logtape/otel';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { BatchLogRecordProcessor, LoggerProvider } from '@opentelemetry/sdk-logs';
import { initializeApiInterceptors } from '#lib/api-interceptors.ts';

const log = getLogger(['integr8scode', 'app']);

export const init: ClientInit = async () => {
    // The sink's own exporter setup doesn't load in a browser
    const loggerProvider = new LoggerProvider({
        processors: [new BatchLogRecordProcessor({ exporter: new OTLPLogExporter({ url: '/otlp/v1/logs' }) })],
    });
    await configure({
        sinks: { otel: getOpenTelemetrySink({ loggerProvider, objectRenderer: 'json' }) },
        loggers: [
            { category: 'integr8scode', sinks: ['otel'] },
            // LogTape reports its own failures here; at warning it skips its startup notice
            { category: ['logtape', 'meta'], lowestLevel: 'warning', sinks: ['otel'] },
        ],
    });
    window.addEventListener('error', ({ error }) => {
        // The browser's own reports, like a ResizeObserver loop, carry no error and break nothing
        if (error) log.error('Uncaught error: {error}', { error });
    });
    window.addEventListener('unhandledrejection', ({ reason }) => {
        log.error('Unhandled rejection: {reason}', { reason });
    });
    initializeApiInterceptors();
};

export const handleError: HandleClientError = ({ kind, error, event }) => {
    log.error('Unexpected {kind} error on {path}: {error}', { kind, path: event.url.pathname, error });
};
