import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail

from users.models import User

from .exceptions import ConfirmationDeliveryError

logger = logging.getLogger(__name__)


def send_confirmation_code(user: User) -> None:
    """Отправить код и проверить доставку письма почтовому backend.

    Ошибки транспорта позволяют повторить signup для существующего
    пользователя. Коды, email и содержимое исключений в лог не попадают.
    """
    logger.info('Confirmation delivery started: user_id=%s', user.pk)
    try:
        sent_count = send_mail(
            subject='Код подтверждения YaMDb',
            message=(
                'Ваш код подтверждения: '
                f'{default_token_generator.make_token(user)}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except (SMTPException, OSError) as error:
        logger.error(
            'Confirmation delivery failed: user_id=%s, error_type=%s',
            user.pk, type(error).__name__,
        )
        raise ConfirmationDeliveryError from error
    if sent_count != 1:
        logger.error(
            'Confirmation delivery incomplete: user_id=%s, sent_count=%s',
            user.pk, sent_count,
        )
        raise ConfirmationDeliveryError
    logger.info('Confirmation delivery completed: user_id=%s', user.pk)
