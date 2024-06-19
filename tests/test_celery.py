from unittest.mock import patch
from application.core.settings import settings
from application.celery_init import make_celery


@patch('application.celery_init.Celery')
def test_make_celery(mock_celery):
    # Arrange
    app_name = 'test_app_name'

    # Act
    celery = make_celery(app_name)

    # Assert
    mock_celery.assert_called_once_with(
        app_name, 
        broker=settings.CELERY_BROKER_URL, 
        backend=settings.CELERY_RESULT_BACKEND
    )
    celery.conf.update.assert_called_once_with(settings)
    assert celery == mock_celery.return_value