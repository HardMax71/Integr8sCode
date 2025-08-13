from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    IntegrationException,
    configure_exception_handlers
)


class TestIntegrationException:

    def test_integration_exception_creation(self) -> None:
        exc = IntegrationException(status_code=400, detail="Bad Request")

        assert exc.status_code == 400
        assert exc.detail == "Bad Request"

    def test_integration_exception_inheritance(self) -> None:
        exc = IntegrationException(status_code=500, detail="Internal Error")

        assert isinstance(exc, Exception)

    def test_integration_exception_different_status_codes(self) -> None:
        exc_400 = IntegrationException(status_code=400, detail="Bad Request")
        exc_404 = IntegrationException(status_code=404, detail="Not Found")
        exc_500 = IntegrationException(status_code=500, detail="Internal Error")

        assert exc_400.status_code == 400
        assert exc_404.status_code == 404
        assert exc_500.status_code == 500

    def test_integration_exception_string_representation(self) -> None:
        exc = IntegrationException(status_code=400, detail="Test error")

        # Should be able to convert to string without error
        str_repr = str(exc)
        assert isinstance(str_repr, str)

    def test_integration_exception_empty_detail(self) -> None:
        exc = IntegrationException(status_code=400, detail="")

        assert exc.status_code == 400
        assert exc.detail == ""

    def test_integration_exception_long_detail(self) -> None:
        long_detail = "This is a very long error message " * 10
        exc = IntegrationException(status_code=500, detail=long_detail)

        assert exc.status_code == 500
        assert exc.detail == long_detail

    def test_integration_exception_can_be_raised(self) -> None:
        with pytest.raises(IntegrationException) as exc_info:
            raise IntegrationException(status_code=400, detail="Test raise")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Test raise"

    def test_integration_exception_attributes_are_accessible(self) -> None:
        try:
            raise IntegrationException(status_code=403, detail="Forbidden")
        except IntegrationException as e:
            assert e.status_code == 403
            assert e.detail == "Forbidden"


class TestConfigureExceptionHandlers:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.app = FastAPI()
        configure_exception_handlers(self.app)

    def test_configure_exception_handlers_adds_handler(self) -> None:
        mock_app = Mock(spec=FastAPI)
        mock_app.exception_handler = Mock()

        configure_exception_handlers(mock_app)

        # Verify exception_handler was called with IntegrationException
        mock_app.exception_handler.assert_called_once()
        call_args = mock_app.exception_handler.call_args
        assert call_args[0][0] == IntegrationException

    @pytest.mark.asyncio
    async def test_integration_exception_handler_function(self) -> None:
        # Create mock request and exception
        mock_request = Mock(spec=Request)
        test_exception = IntegrationException(status_code=400, detail="Test error")

        # Get the handler function from the app's exception handlers
        handler = None
        for exc_type, exc_handler in self.app.exception_handlers.items():
            if exc_type == IntegrationException:
                handler = exc_handler
                break

        assert handler is not None, "IntegrationException handler not found"

        # Call the handler
        response = await handler(mock_request, test_exception)  # type: ignore

        # Verify response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_integration_exception_handler_response_content(self) -> None:
        mock_request = Mock(spec=Request)
        test_exception = IntegrationException(status_code=404, detail="Resource not found")
        handler = self.app.exception_handlers[IntegrationException]
        response = await handler(mock_request, test_exception)  # type: ignore

        # Check response content structure
        assert response.status_code == 404

    def test_configure_exception_handlers_with_different_apps(self) -> None:
        app1 = Mock(spec=FastAPI)
        app1.exception_handler = Mock()
        app2 = Mock(spec=FastAPI)
        app2.exception_handler = Mock()

        configure_exception_handlers(app1)
        configure_exception_handlers(app2)

        # Both apps should have had their exception_handler called
        app1.exception_handler.assert_called_once()
        app2.exception_handler.assert_called_once()

    def test_configure_exception_handlers_idempotent(self) -> None:
        mock_app = Mock(spec=FastAPI)
        mock_app.exception_handler = Mock()

        # Call multiple times
        configure_exception_handlers(mock_app)
        configure_exception_handlers(mock_app)

        # Should be called twice (not idempotent, but shouldn't error)
        assert mock_app.exception_handler.call_count == 2

    @pytest.mark.asyncio
    async def test_integration_exception_handler_different_status_codes(self) -> None:
        """Test handler works with different HTTP status codes."""
        mock_request = Mock(spec=Request)
        handler = self.app.exception_handlers[IntegrationException]

        # Test different status codes
        test_cases = [400, 401, 403, 404, 500, 502]

        for status_code in test_cases:
            test_exception = IntegrationException(
                status_code=status_code,
                detail=f"Error {status_code}"
            )
            response = await handler(mock_request, test_exception)  # type: ignore
            assert response.status_code == status_code

    @pytest.mark.asyncio
    async def test_integration_exception_handler_special_characters(self) -> None:
        mock_request = Mock(spec=Request)
        handler = self.app.exception_handlers[IntegrationException]

        # Test with special characters
        special_detail = "Error with special chars: àáâãäå æç èéêë ìíîï ñ òóôõö ùúûü ý"
        test_exception = IntegrationException(status_code=400, detail=special_detail)

        response = await handler(mock_request, test_exception)  # type: ignore
        assert response.status_code == 400
        assert isinstance(response, JSONResponse)

    def test_configure_exception_handlers_with_none_app(self) -> None:
        # This should raise an AttributeError when trying to call .exception_handler
        with pytest.raises(AttributeError):
            configure_exception_handlers(None)
