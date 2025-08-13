import { writable, derived, get } from 'svelte/store';
import { EventStreamClient, createExecutionEventStream } from '../lib/eventStreamClient.js';
import { api } from '../lib/api.js';

// Store for all executions
export const executions = writable({});

// Store for active EventStream connections
const eventStreams = new Map();

// Store for connection states
export const connectionStates = writable({});

// Store for real-time logs
export const executionLogs = writable({});

// Derived store for execution list as array
export const executionList = derived(
    executions,
    $executions => Object.values($executions).sort((a, b) => 
        new Date(b.created_at || b.timestamp) - new Date(a.created_at || a.timestamp)
    )
);

// Derived store for active executions
export const activeExecutions = derived(
    executions,
    $executions => Object.values($executions).filter(
        exec => ['queued', 'running'].includes(exec.status)
    )
);

// Derived store for completed executions
export const completedExecutions = derived(
    executions,
    $executions => Object.values($executions).filter(
        exec => ['completed', 'failed', 'error'].includes(exec.status)
    )
);

/**
 * Add or update an execution in the store
 */
export function updateExecution(executionId, executionData) {
    executions.update(execs => ({
        ...execs,
        [executionId]: {
            ...execs[executionId],
            ...executionData,
            execution_id: executionId,
            lastUpdated: new Date().toISOString()
        }
    }));
}

/**
 * Remove an execution from the store
 */
export function removeExecution(executionId) {
    // Close any active event stream
    disconnectFromExecution(executionId);
    
    // Remove from stores
    executions.update(execs => {
        const { [executionId]: removed, ...rest } = execs;
        return rest;
    });
    
    executionLogs.update(logs => {
        const { [executionId]: removed, ...rest } = logs;
        return rest;
    });
    
    connectionStates.update(states => {
        const { [executionId]: removed, ...rest } = states;
        return rest;
    });
}

/**
 * Clear all executions
 */
export function clearExecutions() {
    // Close all event streams
    eventStreams.forEach((stream, executionId) => {
        stream.close();
    });
    eventStreams.clear();
    
    // Clear stores
    executions.set({});
    executionLogs.set({});
    connectionStates.set({});
}

/**
 * Connect to real-time updates for an execution
 */
export function connectToExecution(executionId) {
    // Don't connect if already connected
    if (eventStreams.has(executionId)) {
        console.log(`Already connected to execution ${executionId}`);
        return;
    }
    
    // Update connection state
    connectionStates.update(states => ({
        ...states,
        [executionId]: 'connecting'
    }));
    
    // Create event stream
    const stream = createExecutionEventStream(executionId, {
        onOpen: () => {
            console.log(`Connected to execution ${executionId}`);
            connectionStates.update(states => ({
                ...states,
                [executionId]: 'connected'
            }));
        },
        
        onError: (error) => {
            console.error(`Error in execution stream ${executionId}:`, error);
            connectionStates.update(states => ({
                ...states,
                [executionId]: 'error'
            }));
        },
        
        onClose: () => {
            console.log(`Disconnected from execution ${executionId}`);
            connectionStates.update(states => ({
                ...states,
                [executionId]: 'disconnected'
            }));
            eventStreams.delete(executionId);
        },
        
        onReconnect: (attempt) => {
            console.log(`Reconnecting to execution ${executionId} (attempt ${attempt})`);
            connectionStates.update(states => ({
                ...states,
                [executionId]: 'reconnecting'
            }));
        },
        
        onConnected: (event) => {
            const data = JSON.parse(event.data);
            console.log(`Execution ${executionId} connected:`, data);
        },
        
        onStatus: (event) => {
            const data = JSON.parse(event.data);
            console.log(`Execution ${executionId} status update:`, data);
            
            updateExecution(executionId, {
                status: data.status,
                timestamp: data.timestamp
            });
        },
        
        onLog: (event) => {
            const data = JSON.parse(event.data);
            console.log(`Execution ${executionId} log:`, data);
            
            // Append log to execution logs
            executionLogs.update(logs => ({
                ...logs,
                [executionId]: [
                    ...(logs[executionId] || []),
                    {
                        type: data.type || 'output',
                        content: data.content,
                        timestamp: data.timestamp || new Date().toISOString()
                    }
                ]
            }));
        },
        
        onComplete: (event) => {
            const data = JSON.parse(event.data);
            console.log(`Execution ${executionId} completed:`, data);
            
            updateExecution(executionId, {
                status: data.status || 'completed',
                completedAt: data.timestamp,
                // Don't set output/errors here - wait for fetchExecution to get the real data
                needsFetch: true
            });
            
            // Auto-disconnect after completion
            setTimeout(() => {
                disconnectFromExecution(executionId);
            }, 10000);
        }
    });
    
    // Store the stream
    eventStreams.set(executionId, stream);
    
    // Connect
    stream.connect();
}

/**
 * Disconnect from real-time updates for an execution
 */
export function disconnectFromExecution(executionId) {
    const stream = eventStreams.get(executionId);
    if (stream) {
        stream.close();
        eventStreams.delete(executionId);
    }
}

/**
 * Fetch execution details from API
 */
export async function fetchExecution(executionId) {
    try {
        const data = await api.get(`/api/v1/result/${executionId}`);
        
        // The backend already parsed the executor JSON and stored the actual values
        // We just need to use them directly
        updateExecution(executionId, {
            status: data.status,
            output: data.output || '',
            errors: data.errors || '',
            exitCode: data.exit_code,
            errorType: data.error_type,
            executionTime: data.execution_time,
            resourceUsage: data.resource_usage,
            needsFetch: false
        });
        
        return data;
    } catch (error) {
        console.error(`Error fetching execution ${executionId}:`, error);
        throw error;
    }
}

/**
 * Create a new execution
 */
export async function createExecution(script, language, languageVersion) {
    // Check if authenticated
    const { isAuthenticated } = await import('./auth.js');
    const { get } = await import('svelte/store');
    
    if (!get(isAuthenticated)) {
        throw new Error('Not authenticated. Please login first.');
    }
    
    try {
        const data = await api.post('/api/v1/execute', {
            script,
            lang: language,
            lang_version: languageVersion
        });
        
        const executionId = data.execution_id;
        
        // Add to store
        updateExecution(executionId, {
            status: data.status || 'queued',
            script,
            language,
            languageVersion,
            createdAt: new Date().toISOString()
        });
        
        // Connect to real-time updates
        connectToExecution(executionId);
        
        return executionId;
    } catch (error) {
        console.error('Error creating execution:', error);
        throw error;
    }
}

/**
 * Fetch user's recent executions
 */
export async function fetchRecentExecutions(limit = 10) {
    try {
        const data = await api.get(`/api/v1/events/user?limit=${limit}`);
        
        // Process events to extract execution information
        const executionMap = {};
        
        data.events.forEach(event => {
            const execId = event.aggregate_id || event.payload?.execution_id;
            if (!execId) return;
            
            if (!executionMap[execId]) {
                executionMap[execId] = {
                    execution_id: execId,
                    status: 'unknown',
                    createdAt: event.timestamp,
                    events: []
                };
            }
            
            executionMap[execId].events.push(event);
            
            // Update execution based on event type
            if (event.event_type === 'execution.queued') {
                executionMap[execId].script = event.payload.script;
                executionMap[execId].language = event.payload.language;
                executionMap[execId].languageVersion = event.payload.language_version;
                executionMap[execId].status = 'queued';
            } else if (event.event_type === 'execution.started') {
                executionMap[execId].status = 'running';
                executionMap[execId].startedAt = event.timestamp;
            } else if (event.event_type === 'execution.completed') {
                executionMap[execId].status = 'completed';
                executionMap[execId].completedAt = event.timestamp;
            } else if (event.event_type === 'execution.failed') {
                executionMap[execId].status = 'failed';
                executionMap[execId].completedAt = event.timestamp;
            }
        });
        
        // Update store with fetched executions
        Object.values(executionMap).forEach(exec => {
            updateExecution(exec.execution_id, exec);
        });
        
        return Object.values(executionMap);
    } catch (error) {
        console.error('Error fetching recent executions:', error);
        throw error;
    }
}

/**
 * Get execution state helper
 */
export function getExecutionState(executionId) {
    const $executions = get(executions);
    const $connectionStates = get(connectionStates);
    const $executionLogs = get(executionLogs);
    
    return {
        execution: $executions[executionId],
        connectionState: $connectionStates[executionId] || 'disconnected',
        logs: $executionLogs[executionId] || []
    };
}

/**
 * Subscribe to execution updates
 */
export function subscribeToExecution(executionId, callback) {
    // Auto-connect if not connected
    if (!eventStreams.has(executionId)) {
        connectToExecution(executionId);
    }
    
    // Return unsubscribe function
    return executions.subscribe($executions => {
        const execution = $executions[executionId];
        if (execution) {
            callback(execution);
        }
    });
}