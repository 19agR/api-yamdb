"""Поля сериализаторов с нормализацией пользовательских данных."""

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from users.validators import username_validator

User = get_user_model()


class NormalizedEmailField(serializers.EmailField):
    """Нормализовать доменную часть адреса до проверки валидаторов."""

    def to_internal_value(self, data: Any) -> str:
        """Привести электронный адрес к формату модели пользователя."""
        return User.objects.normalize_email(super().to_internal_value(data))


class NormalizedUsernameField(serializers.CharField):
    """Нормализовать имя, сохраняя общую проверку допустимых символов."""

    def to_internal_value(self, data: Any) -> str:
        """Проверить и нормализовать переданное имя пользователя."""
        value = super().to_internal_value(data)
        username_validator(value)
        return User.normalize_username(value)
