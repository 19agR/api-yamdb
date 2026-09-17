from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_year(value: int) -> None:
    """Отклонить год выпуска позже текущего."""
    if value > timezone.now().year:
        raise ValidationError('Год выпуска не может быть позже текущего.')
