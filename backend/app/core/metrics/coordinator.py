from app.core.metrics.base import BaseMetrics


class CoordinatorMetrics(BaseMetrics):
    """Metrics for coordinator and scheduling operations."""
    
    def _create_instruments(self) -> None:
        # Coordinator processing metrics
        self.coordinator_processing_time = self._meter.create_histogram(
            name="coordinator.processing.time",
            description="Time spent processing execution events in seconds",
            unit="s"
        )
        
        self.coordinator_scheduling_duration = self._meter.create_histogram(
            name="coordinator.scheduling.duration",
            description="Time spent scheduling executions in seconds",
            unit="s"
        )
        
        self.coordinator_active_executions = self._meter.create_up_down_counter(
            name="coordinator.executions.active",
            description="Number of active executions managed by coordinator",
            unit="1"
        )
        
        # Queue management metrics
        self.coordinator_queue_time = self._meter.create_histogram(
            name="coordinator.queue.wait_time",
            description="Time spent waiting in coordinator queue by priority",
            unit="s"
        )
        
        self.coordinator_queue_operations = self._meter.create_counter(
            name="coordinator.queue.operations.total",
            description="Total queue operations (add/remove)",
            unit="1"
        )

        # Execution-only request queue depth (authoritative, maintained by coordinator)
        self.execution_request_queue_depth = self._meter.create_up_down_counter(
            name="execution.queue.depth",
            description="Depth of user execution requests queued (excludes replays and non-request events)",
            unit="1"
        )
        
        # Scheduling metrics
        self.coordinator_executions_scheduled = self._meter.create_counter(
            name="coordinator.executions.scheduled.total",
            description="Total number of executions scheduled",
            unit="1"
        )
        
        # Rate limiting metrics
        self.coordinator_rate_limited = self._meter.create_counter(
            name="coordinator.rate_limited.total",
            description="Total number of rate-limited requests",
            unit="1"
        )
        
        self.coordinator_rate_limit_wait_time = self._meter.create_histogram(
            name="coordinator.rate_limit.wait_time",
            description="Time clients wait due to rate limiting",
            unit="s"
        )
        
        # Resource management metrics
        self.coordinator_resource_allocations = self._meter.create_counter(
            name="coordinator.resource.allocations.total",
            description="Total number of resource allocations",
            unit="1"
        )
        
        self.coordinator_resource_utilization = self._meter.create_up_down_counter(
            name="coordinator.resource.utilization",
            description="Current resource utilization",
            unit="1"
        )
        
        # Scheduling decision metrics
        self.coordinator_scheduling_decisions = self._meter.create_counter(
            name="coordinator.scheduling.decisions.total",
            description="Total scheduling decisions made",
            unit="1"
        )
    
    def record_coordinator_processing_time(self, duration_seconds: float) -> None:
        self.coordinator_processing_time.record(duration_seconds)
    
    def record_scheduling_duration(self, duration_seconds: float) -> None:
        self.coordinator_scheduling_duration.record(duration_seconds)
    
    def update_active_executions_gauge(self, count: int) -> None:
        """Update the count of active executions (absolute value)."""
        # Reset to 0 then set to new value (for gauge-like behavior)
        # This is a workaround since we're using up_down_counter
        current_val = getattr(self, '_active_executions_current', 0)
        delta = count - current_val
        if delta != 0:
            self.coordinator_active_executions.add(delta)
        self._active_executions_current = count
    
    def record_coordinator_queue_time(self, wait_seconds: float, priority: str) -> None:
        self.coordinator_queue_time.record(
            wait_seconds,
            attributes={"priority": priority}
        )
    
    def record_coordinator_execution_scheduled(self, status: str) -> None:
        self.coordinator_executions_scheduled.add(
            1,
            attributes={"status": status}
        )
    
    def record_coordinator_scheduling_duration(self, duration_seconds: float) -> None:
        self.coordinator_scheduling_duration.record(duration_seconds)
    
    def update_coordinator_active_executions(self, count: int) -> None:
        self.update_active_executions_gauge(count)
    
    def record_queue_wait_time_by_priority(self, wait_seconds: float, priority: str, queue_name: str) -> None:
        self.coordinator_queue_time.record(
            wait_seconds,
            attributes={
                "priority": priority,
                "queue": queue_name
            }
        )
    
    # Removed legacy coordinator.queue.size; use execution.queue.depth instead

    def update_execution_request_queue_size(self, size: int) -> None:
        """Update the execution-only request queue depth (absolute value)."""
        key = '_exec_request_queue_size'
        current_val = getattr(self, key, 0)
        delta = size - current_val
        if delta != 0:
            self.execution_request_queue_depth.add(delta)
        setattr(self, key, size)
    
    def record_rate_limited(self, limit_type: str, user_id: str) -> None:
        self.coordinator_rate_limited.add(
            1,
            attributes={
                "limit_type": limit_type,
                "user_id": user_id
            }
        )
    
    def update_rate_limit_wait_time(self, limit_type: str, user_id: str, wait_seconds: float) -> None:
        self.coordinator_rate_limit_wait_time.record(
            wait_seconds,
            attributes={
                "limit_type": limit_type,
                "user_id": user_id
            }
        )
    
    def record_resource_allocation(self, resource_type: str, amount: float, execution_id: str) -> None:
        self.coordinator_resource_allocations.add(
            1,
            attributes={
                "resource_type": resource_type,
                "execution_id": execution_id
            }
        )
        
        # Update gauge for current allocation
        key = f'_resource_{resource_type}'
        current_val = getattr(self, key, 0.0)
        new_val = current_val + amount
        setattr(self, key, new_val)
    
    def record_resource_release(self, resource_type: str, amount: float, execution_id: str) -> None:
        self.coordinator_resource_allocations.add(
            -1,
            attributes={
                "resource_type": resource_type,
                "execution_id": execution_id
            }
        )
        
        # Update gauge for current allocation
        key = f'_resource_{resource_type}'
        current_val = getattr(self, key, 0.0)
        new_val = max(0.0, current_val - amount)
        setattr(self, key, new_val)
    
    def update_resource_usage(self, resource_type: str, usage_percent: float) -> None:
        # Record as a gauge-like metric
        key = f'_resource_usage_{resource_type}'
        current_val = getattr(self, key, 0.0)
        delta = usage_percent - current_val
        if delta != 0:
            self.coordinator_resource_utilization.add(
                delta,
                attributes={"resource_type": resource_type}
            )
        setattr(self, key, usage_percent)
    
    def record_scheduling_decision(self, decision: str, reason: str) -> None:
        self.coordinator_scheduling_decisions.add(
            1,
            attributes={
                "decision": decision,
                "reason": reason
            }
        )
    
    def record_queue_reordering(self, queue_name: str, items_moved: int) -> None:
        self.coordinator_queue_operations.add(
            1,
            attributes={
                "operation": "reorder",
                "queue": queue_name
            }
        )
        
        # Record the number of items moved as a histogram
        self.coordinator_queue_time.record(
            float(items_moved),
            attributes={
                "priority": "reordered",
                "queue": queue_name
            }
        )
    
    def record_priority_change(self, execution_id: str, old_priority: str, new_priority: str) -> None:
        self.coordinator_scheduling_decisions.add(
            1,
            attributes={
                "decision": "priority_change",
                "reason": f"{old_priority}_to_{new_priority}"
            }
        )
    
    def update_rate_limiter_tokens(self, limit_type: str, tokens: int) -> None:
        # Track tokens as gauge-like metric
        key = f'_rate_limiter_{limit_type}'
        current_val = getattr(self, key, 0)
        delta = tokens - current_val
        if delta != 0:
            self.coordinator_resource_utilization.add(
                delta,
                attributes={"resource_type": f"rate_limit_{limit_type}"}
            )
        setattr(self, key, tokens)
    
    def record_rate_limit_reset(self, limit_type: str, user_id: str) -> None:
        self.coordinator_scheduling_decisions.add(
            1,
            attributes={
                "decision": "rate_limit_reset",
                "reason": f"{limit_type}_for_{user_id}"
            }
        )
