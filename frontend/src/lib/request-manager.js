class RequestManager {
    constructor() {
        this.pendingRequests = new Map();
        this.cache = new Map();
        this.cacheConfig = {
            '/api/v1/notifications': { ttl: 10000 }, // 10 seconds
            '/api/v1/notifications/unread-count': { ttl: 10000 }, // 10 seconds
            '/api/v1/k8s-limits': { ttl: 300000 }, // 5 minutes
            '/api/v1/example-scripts': { ttl: 600000 }, // 10 minutes
            '/api/v1/scripts': { ttl: 15000 }, // 15 seconds
            '/api/v1/auth/verify-token': { ttl: 30000 } // 30 seconds - handled in auth store
        };
    }

    getCacheKey(url, options = {}) {
        return `${url}:${JSON.stringify(options)}`;
    }

    getCachedData(key) {
        const cached = this.cache.get(key);
        if (cached && Date.now() - cached.timestamp < cached.ttl) {
            return cached.data;
        }
        this.cache.delete(key);
        return null;
    }

    setCachedData(key, data, ttl) {
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl
        });
    }

    async dedupedRequest(url, fetcher, options = {}) {
        const cacheKey = this.getCacheKey(url, options);
        
        // Check cache first
        const cachedData = this.getCachedData(cacheKey);
        if (cachedData !== null) {
            return cachedData;
        }

        // Check if request is already pending
        const pending = this.pendingRequests.get(cacheKey);
        if (pending) {
            return pending;
        }

        // Make the request
        const requestPromise = fetcher()
            .then(data => {
                // Cache the result - find the best matching endpoint
                let matchedEndpoint = null;
                let longestMatch = 0;
                
                for (const endpoint of Object.keys(this.cacheConfig)) {
                    if (url.includes(endpoint) && endpoint.length > longestMatch) {
                        matchedEndpoint = endpoint;
                        longestMatch = endpoint.length;
                    }
                }
                
                if (matchedEndpoint && this.cacheConfig[matchedEndpoint]) {
                    this.setCachedData(cacheKey, data, this.cacheConfig[matchedEndpoint].ttl);
                }
                this.pendingRequests.delete(cacheKey);
                return data;
            })
            .catch(error => {
                this.pendingRequests.delete(cacheKey);
                throw error;
            });

        this.pendingRequests.set(cacheKey, requestPromise);
        return requestPromise;
    }

    clearCache(pattern = null) {
        if (!pattern) {
            this.cache.clear();
        } else {
            for (const key of this.cache.keys()) {
                if (key.includes(pattern)) {
                    this.cache.delete(key);
                }
            }
        }
    }

    clearPendingRequests() {
        this.pendingRequests.clear();
    }
}

export const requestManager = new RequestManager();