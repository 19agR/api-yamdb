from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .constants import RESERVED_USERNAME, USERNAME_PATTERN


username_validator = RegexValidator(
    regex=USERNAME_PATTERN,
    message='Используйте только буквы, цифры и символы @/./+/-/_.',
)


def validate_username(value: str) -> None:
    """Отклонить зарезервированное имя профиля."""
    if value == RESERVED_USERNAME:
        raise ValidationError(
            f'Имя пользователя {RESERVED_USERNAME} зарезервировано.',
        )
