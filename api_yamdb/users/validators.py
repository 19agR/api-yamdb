from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator


username_validator = RegexValidator(
    regex=r'^[\w.@+-]+\Z',
    message='Используйте только буквы, цифры и символы @/./+/-/_.',
)


def validate_username(value: str) -> None:
    """Отклонить зарезервированное имя профиля."""
    if value.lower() == 'me':
        raise ValidationError('Имя пользователя me зарезервировано.')
