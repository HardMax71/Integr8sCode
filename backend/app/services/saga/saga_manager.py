"""Saga orchestrator manager for dependency injection"""

from typing import Optional

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.services.saga.execution_saga import ExecutionSaga
from app.services.saga.saga_orchestrator import SagaConfig, SagaOrchestrator


class SagaOrchestratorManager:
    """Manages saga orchestrator lifecycle"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager
        self._orchestrator: Optional[SagaOrchestrator] = None
        self._initialized = False

    async def get_orchestrator(self) -> SagaOrchestrator:
        """Get or create saga orchestrator instance"""
        if self._orchestrator is None:
            # Create configuration
            config = SagaConfig(
                name="main-orchestrator",
                timeout_seconds=300,
                max_retries=3,
                retry_delay_seconds=5,
                enable_compensation=True,
                store_events=True
            )

            # Create orchestrator
            if not self.db_manager:
                raise RuntimeError("DatabaseManager not provided to SagaOrchestratorManager")
            self._orchestrator = SagaOrchestrator(config, db_manager=self.db_manager)

            # Register sagas
            self._orchestrator.register_saga(ExecutionSaga)

            # Start orchestrator
            await self._orchestrator.start()
            self._initialized = True

            logger.info("Saga orchestrator initialized and started")

        return self._orchestrator

    async def shutdown(self) -> None:
        """Shutdown saga orchestrator"""
        if self._orchestrator and self._initialized:
            await self._orchestrator.stop()
            self._orchestrator = None
            self._initialized = False
            logger.info("Saga orchestrator shut down")


class SagaOrchestratorManagerSingleton:
    """Singleton wrapper for SagaOrchestratorManager"""
    _instance: Optional[SagaOrchestratorManager] = None
    _db_manager: Optional[DatabaseManager] = None

    @classmethod
    def set_database_manager(cls, db_manager: DatabaseManager) -> None:
        """Set the database manager for the singleton"""
        cls._db_manager = db_manager

    @classmethod
    def get_instance(cls) -> SagaOrchestratorManager:
        if cls._instance is None:
            if cls._db_manager is None:
                raise RuntimeError("DatabaseManager not set for SagaOrchestratorManagerSingleton")
            cls._instance = SagaOrchestratorManager(db_manager=cls._db_manager)
        return cls._instance


async def get_saga_orchestrator_manager() -> SagaOrchestratorManager:
    """Get saga orchestrator manager instance"""
    return SagaOrchestratorManagerSingleton.get_instance()
