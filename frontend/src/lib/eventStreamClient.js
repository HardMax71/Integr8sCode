export class EventStreamClient {
    constructor(url, options = {}) {
        this.url = url;
        this.options = {
            withCredentials: true,
            reconnectDelay: 1000,
            maxReconnectDelay: 30000,
            reconnectDelayMultiplier: 1.5,
            maxReconnectAttempts: 10, // increased reconnection attempts
            heartbeatTimeout: 20000, // 20 seconds (considering 10s heartbeat interval)
            onOpen: () => {},
            onError: () => {},
            onClose: () => {},
            onMessage: () => {},
            onReconnect: () => {},
            ...options
        };
        
        this.eventSource = null;
        this.reconnectAttempts = 0;
        this.reconnectDelay = this.options.reconnectDelay;
        this.reconnectTimer = null;
        this.heartbeatTimer = null;
        this.lastHeartbeat = Date.now();
        this.connectionState = 'disconnected'; // disconnected, connecting, connected
        this.eventHandlers = new Map();
        this.closed = false;
    }
    
    /**
     * Connect to the event stream
     */
    connect() {
        if (this.closed) {
            console.warn('EventStreamClient: Cannot connect after close()');
            return;
        }
        
        if (this.eventSource && this.eventSource.readyState !== EventSource.CLOSED) {
            console.warn('EventStreamClient: Already connected');
            return;
        }
        
        this.connectionState = 'connecting';
        this._createEventSource();
    }
    
    /**
     * Close the connection and cleanup
     */
    close() {
        this.closed = true;
        this.connectionState = 'disconnected';
        
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        
        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
        
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        
        this.options.onClose();
    }
    
    /**
     * Add event listener for specific event types
     */
    addEventListener(eventType, handler) {
        if (!this.eventHandlers.has(eventType)) {
            this.eventHandlers.set(eventType, new Set());
        }
        this.eventHandlers.get(eventType).add(handler);
        
        // Add to current EventSource if connected
        if (this.eventSource && this.eventSource.readyState !== EventSource.CLOSED) {
            this.eventSource.addEventListener(eventType, handler);
        }
    }
    
    /**
     * Remove event listener
     */
    removeEventListener(eventType, handler) {
        if (this.eventHandlers.has(eventType)) {
            this.eventHandlers.get(eventType).delete(handler);
            
            if (this.eventHandlers.get(eventType).size === 0) {
                this.eventHandlers.delete(eventType);
            }
        }
        
        // Remove from current EventSource if connected
        if (this.eventSource) {
            this.eventSource.removeEventListener(eventType, handler);
        }
    }
    
    /**
     * Get current connection state
     */
    getState() {
        return this.connectionState;
    }
    
    /**
     * Create and setup EventSource
     */
    _createEventSource() {
        try {
            // No need to add token - using httpOnly cookies
            this.eventSource = new EventSource(this.url, {
                withCredentials: this.options.withCredentials
            });
            
            // Setup event handlers
            this.eventSource.onopen = (event) => {
                console.log('EventStreamClient: Connection opened');
                this.connectionState = 'connected';
                this.reconnectAttempts = 0;
                this.reconnectDelay = this.options.reconnectDelay;
                this.lastHeartbeat = Date.now();
                this._startHeartbeatMonitor();
                this.options.onOpen(event);
            };
            
            this.eventSource.onerror = (event) => {
                console.error('EventStreamClient: Connection error', event);
                this.connectionState = 'disconnected';
                this.options.onError(event);
                
                if (this.eventSource.readyState === EventSource.CLOSED) {
                    this._handleDisconnection();
                }
            };
            
            this.eventSource.onmessage = (event) => {
                this.options.onMessage(event);
            };
            
            // Re-attach all registered event handlers
            for (const [eventType, handlers] of this.eventHandlers) {
                for (const handler of handlers) {
                    this.eventSource.addEventListener(eventType, handler);
                }
            }
            
            // Handle heartbeat events
            this.eventSource.addEventListener('heartbeat', (event) => {
                this.lastHeartbeat = Date.now();
                console.debug('EventStreamClient: Heartbeat received');
            });
            
        } catch (error) {
            console.error('EventStreamClient: Failed to create EventSource', error);
            this.connectionState = 'disconnected';
            this._handleDisconnection();
        }
    }
    
    /**
     * Handle disconnection and reconnection logic
     */
    _handleDisconnection() {
        if (this.closed) {
            return;
        }
        
        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
        
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        
        // Check if we should attempt reconnection
        if (this.options.maxReconnectAttempts !== null && 
            this.reconnectAttempts >= this.options.maxReconnectAttempts) {
            console.error('EventStreamClient: Max reconnection attempts reached');
            this.close();
            return;
        }
        
        // Schedule reconnection
        this.reconnectAttempts++;
        console.log(`EventStreamClient: Reconnecting in ${this.reconnectDelay}ms (attempt ${this.reconnectAttempts})`);
        
        this.options.onReconnect(this.reconnectAttempts);
        
        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, this.reconnectDelay);
        
        // Increase delay for next attempt
        this.reconnectDelay = Math.min(
            this.reconnectDelay * this.options.reconnectDelayMultiplier,
            this.options.maxReconnectDelay
        );
    }
    
    /**
     * Monitor heartbeat to detect stale connections
     */
    _startHeartbeatMonitor() {
        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
        }
        
        this.heartbeatTimer = setTimeout(() => {
            const timeSinceLastHeartbeat = Date.now() - this.lastHeartbeat;
            
            if (timeSinceLastHeartbeat > this.options.heartbeatTimeout) {
                console.warn('EventStreamClient: Heartbeat timeout, reconnecting...');
                this._handleDisconnection();
            } else {
                // Continue monitoring
                this._startHeartbeatMonitor();
            }
        }, this.options.heartbeatTimeout);
    }
}

/**
 * Create an EventStreamClient for execution updates
 */
export function createExecutionEventStream(executionId, handlers = {}) {
    const url = `/api/v1/events/executions/${executionId}`;
    
    const client = new EventStreamClient(url, {
        onOpen: handlers.onOpen || (() => console.log('Execution event stream connected')),
        onError: handlers.onError || ((error) => console.error('Execution event stream error:', error)),
        onClose: handlers.onClose || (() => console.log('Execution event stream closed')),
        onMessage: handlers.onMessage || ((event) => console.log('Execution event:', event)),
        onReconnect: handlers.onReconnect || ((attempt) => console.log(`Reconnecting... (attempt ${attempt})`))
    });
    
    // Add specific event handlers
    if (handlers.onStatus) {
        client.addEventListener('status', handlers.onStatus);
    }
    
    if (handlers.onLog) {
        client.addEventListener('log', handlers.onLog);
    }
    
    if (handlers.onComplete) {
        client.addEventListener('complete', handlers.onComplete);
    }
    
    if (handlers.onConnected) {
        client.addEventListener('connected', handlers.onConnected);
    }
    
    return client;
}