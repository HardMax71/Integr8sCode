from app.core.container import create_result_processor_container
from app.events.handlers import register_result_processor_subscriber

from workers.bootstrap import run_worker


def main() -> None:
    """Main entry point for result processor worker"""
    run_worker(
        worker_name="ResultProcessor",
        config_override="config.result-processor.toml",
        container_factory=create_result_processor_container,
        register_handlers=register_result_processor_subscriber,
    )


if __name__ == "__main__":
    main()
