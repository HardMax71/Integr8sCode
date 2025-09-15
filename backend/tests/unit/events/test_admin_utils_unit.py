"""Unit tests for admin_utils.py with high coverage."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import pytest
from confluent_kafka.admin import AdminClient, NewTopic

from app.events.admin_utils import AdminUtils, create_admin_utils


class TestAdminUtils:
    @pytest.fixture
    def mock_admin_client(self):
        """Create a mock admin client."""
        with patch('app.events.admin_utils.AdminClient') as mock:
            yield mock

    @pytest.fixture
    def mock_settings(self):
        """Mock settings."""
        with patch('app.events.admin_utils.get_settings') as mock:
            settings = MagicMock()
            settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
            mock.return_value = settings
            yield mock

    @pytest.fixture
    def admin_utils(self, mock_admin_client, mock_settings):
        """Create AdminUtils instance with mocked dependencies."""
        return AdminUtils()

    def test_init_with_custom_bootstrap_servers(self, mock_admin_client, mock_settings):
        """Test initialization with custom bootstrap servers."""
        admin = AdminUtils(bootstrap_servers="custom:9092")
        mock_admin_client.assert_called_once_with({
            'bootstrap.servers': 'custom:9092',
            'client.id': 'integr8scode-admin'
        })

    def test_init_with_default_bootstrap_servers(self, mock_admin_client, mock_settings):
        """Test initialization with default bootstrap servers from settings."""
        admin = AdminUtils()
        mock_admin_client.assert_called_once_with({
            'bootstrap.servers': 'localhost:9092',
            'client.id': 'integr8scode-admin'
        })

    def test_admin_client_property(self, admin_utils, mock_admin_client):
        """Test admin_client property returns the client."""
        result = admin_utils.admin_client
        assert result == mock_admin_client.return_value

    @pytest.mark.asyncio
    async def test_check_topic_exists_success(self, admin_utils, mock_admin_client):
        """Test check_topic_exists when topic exists."""
        # Mock metadata
        metadata = MagicMock()
        metadata.topics = {'test-topic': None, 'another-topic': None}
        mock_admin_client.return_value.list_topics.return_value = metadata

        result = await admin_utils.check_topic_exists('test-topic')
        assert result is True
        mock_admin_client.return_value.list_topics.assert_called_once_with(timeout=5.0)

    @pytest.mark.asyncio
    async def test_check_topic_exists_not_found(self, admin_utils, mock_admin_client):
        """Test check_topic_exists when topic doesn't exist."""
        # Mock metadata
        metadata = MagicMock()
        metadata.topics = {'another-topic': None}
        mock_admin_client.return_value.list_topics.return_value = metadata

        result = await admin_utils.check_topic_exists('test-topic')
        assert result is False

    @pytest.mark.asyncio
    async def test_check_topic_exists_exception(self, admin_utils, mock_admin_client):
        """Test check_topic_exists when exception occurs."""
        mock_admin_client.return_value.list_topics.side_effect = Exception("Connection failed")

        result = await admin_utils.check_topic_exists('test-topic')
        assert result is False
        mock_admin_client.return_value.list_topics.assert_called_once_with(timeout=5.0)

    @pytest.mark.asyncio
    async def test_create_topic_success(self, admin_utils, mock_admin_client):
        """Test create_topic successful creation."""
        # Mock the future
        future = MagicMock()
        future.result.return_value = None  # Success returns None
        futures = {'test-topic': future}
        mock_admin_client.return_value.create_topics.return_value = futures

        with patch('asyncio.get_event_loop') as mock_loop:
            mock_executor = AsyncMock()
            mock_loop.return_value.run_in_executor = mock_executor
            mock_executor.return_value = None

            result = await admin_utils.create_topic('test-topic', num_partitions=3, replication_factor=2)
            assert result is True

            # Verify create_topics was called correctly
            mock_admin_client.return_value.create_topics.assert_called_once()
            call_args = mock_admin_client.return_value.create_topics.call_args
            topics = call_args[0][0]
            assert len(topics) == 1
            assert isinstance(topics[0], NewTopic)
            assert call_args[1]['operation_timeout'] == 30.0

    @pytest.mark.asyncio
    async def test_create_topic_failure(self, admin_utils, mock_admin_client):
        """Test create_topic when creation fails."""
        # Mock the future to raise an exception
        future = MagicMock()
        future.result.side_effect = Exception("Topic already exists")
        futures = {'test-topic': future}
        mock_admin_client.return_value.create_topics.return_value = futures

        with patch('asyncio.get_event_loop') as mock_loop:
            mock_executor = AsyncMock()
            mock_loop.return_value.run_in_executor = mock_executor
            mock_executor.side_effect = Exception("Topic already exists")

            result = await admin_utils.create_topic('test-topic')
            assert result is False

    @pytest.mark.asyncio
    async def test_create_topic_exception_during_creation(self, admin_utils, mock_admin_client):
        """Test create_topic when exception occurs during topic creation."""
        mock_admin_client.return_value.create_topics.side_effect = Exception("Kafka unavailable")

        result = await admin_utils.create_topic('test-topic')
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_topics_exist_all_exist(self, admin_utils):
        """Test ensure_topics_exist when all topics already exist."""
        topics = [('topic1', 1), ('topic2', 2)]

        with patch.object(admin_utils, 'check_topic_exists', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True

            results = await admin_utils.ensure_topics_exist(topics)
            assert results == {'topic1': True, 'topic2': True}
            assert mock_check.call_count == 2

    @pytest.mark.asyncio
    async def test_ensure_topics_exist_create_missing(self, admin_utils):
        """Test ensure_topics_exist when some topics need to be created."""
        topics = [('topic1', 1), ('topic2', 2), ('topic3', 3)]

        with patch.object(admin_utils, 'check_topic_exists', new_callable=AsyncMock) as mock_check:
            # topic1 exists, topic2 and topic3 don't
            mock_check.side_effect = [True, False, False]

            with patch.object(admin_utils, 'create_topic', new_callable=AsyncMock) as mock_create:
                # topic2 creation succeeds, topic3 fails
                mock_create.side_effect = [True, False]

                results = await admin_utils.ensure_topics_exist(topics)
                assert results == {'topic1': True, 'topic2': True, 'topic3': False}

                # Verify create_topic was called for missing topics
                assert mock_create.call_count == 2
                mock_create.assert_any_call('topic2', 2)
                mock_create.assert_any_call('topic3', 3)

    @pytest.mark.asyncio
    async def test_ensure_topics_exist_empty_list(self, admin_utils):
        """Test ensure_topics_exist with empty topic list."""
        results = await admin_utils.ensure_topics_exist([])
        assert results == {}

    def test_get_admin_client(self, admin_utils, mock_admin_client):
        """Test get_admin_client returns the admin client."""
        result = admin_utils.get_admin_client()
        assert result == mock_admin_client.return_value


class TestCreateAdminUtils:
    def test_create_admin_utils_default(self):
        """Test create_admin_utils with default parameters."""
        with patch('app.events.admin_utils.AdminUtils') as mock_class:
            result = create_admin_utils()
            mock_class.assert_called_once_with(None)
            assert result == mock_class.return_value

    def test_create_admin_utils_with_bootstrap_servers(self):
        """Test create_admin_utils with custom bootstrap servers."""
        with patch('app.events.admin_utils.AdminUtils') as mock_class:
            result = create_admin_utils("custom:9092")
            mock_class.assert_called_once_with("custom:9092")
            assert result == mock_class.return_value


class TestAdminUtilsIntegration:
    """Integration tests with more realistic mocking."""

    @pytest.mark.asyncio
    async def test_full_topic_lifecycle(self):
        """Test the full lifecycle of topic management."""
        with patch('app.events.admin_utils.AdminClient') as mock_admin_client:
            with patch('app.events.admin_utils.get_settings') as mock_settings:
                settings = MagicMock()
                settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
                mock_settings.return_value = settings

                # Setup metadata mock
                metadata = MagicMock()
                metadata.topics = {}
                mock_admin_client.return_value.list_topics.return_value = metadata

                # Setup create_topics mock
                future = MagicMock()
                future.result.return_value = None
                futures = {'new-topic': future}
                mock_admin_client.return_value.create_topics.return_value = futures

                admin = AdminUtils()

                # Topic doesn't exist initially
                exists = await admin.check_topic_exists('new-topic')
                assert exists is False

                # Create the topic
                with patch('asyncio.get_event_loop') as mock_loop:
                    mock_executor = AsyncMock()
                    mock_loop.return_value.run_in_executor = mock_executor
                    mock_executor.return_value = None

                    created = await admin.create_topic('new-topic', num_partitions=4)
                    assert created is True

                # Now add it to metadata
                metadata.topics['new-topic'] = None

                # Check it exists
                exists = await admin.check_topic_exists('new-topic')
                assert exists is True

    @pytest.mark.asyncio
    async def test_concurrent_topic_creation(self):
        """Test concurrent topic creation handling."""
        with patch('app.events.admin_utils.AdminClient') as mock_admin_client:
            with patch('app.events.admin_utils.get_settings') as mock_settings:
                settings = MagicMock()
                settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
                mock_settings.return_value = settings

                admin = AdminUtils()

                # Mock check_topic_exists to return False
                with patch.object(admin, 'check_topic_exists', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = False

                    # Mock create_topic to simulate concurrent creation
                    with patch.object(admin, 'create_topic', new_callable=AsyncMock) as mock_create:
                        # First call succeeds, second fails (already exists)
                        mock_create.side_effect = [True, False, True]

                        topics = [('topic1', 1), ('topic2', 2), ('topic3', 3)]
                        results = await admin.ensure_topics_exist(topics)

                        assert results['topic1'] is True
                        assert results['topic2'] is False
                        assert results['topic3'] is True