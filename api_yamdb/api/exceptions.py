from http import HTTPStatus

from rest_framework.exceptions import APIException, ValidationError


class ConfirmationDeliveryError(APIException):
    """Сообщить о временной невозможности отправить код подтверждения."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_detail = 'Не удалось отправить код. Повторите запрос позже.'
    default_code = 'confirmation_delivery_failed'


class DuplicateReviewError(ValidationError):
    """Отклонить второй отзыв одного автора на произведение."""

    default_detail = 'Вы уже оставили отзыв на это произведение.'
    default_code = 'duplicate_review'
