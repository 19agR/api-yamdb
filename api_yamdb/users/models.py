from django.contrib.auth.models import AbstractUser
from django.db import models

from .constants import EMAIL_MAX_LENGTH, USERNAME_MAX_LENGTH
from .validators import username_validator, validate_username


class User(AbstractUser):
    """Хранить профиль пользователя и роль в API."""

    class Role(models.TextChoices):
        """Перечислить доступные роли пользователя."""

        USER = 'user', 'Пользователь'
        MODERATOR = 'moderator', 'Модератор'
        ADMIN = 'admin', 'Администратор'

    username = models.CharField(
        'Имя пользователя',
        max_length=USERNAME_MAX_LENGTH,
        unique=True,
        validators=[username_validator, validate_username],
    )
    email = models.EmailField(
        'Электронная почта', unique=True, max_length=EMAIL_MAX_LENGTH,
    )
    bio = models.TextField('О себе', blank=True)
    role = models.CharField(
        'Роль', max_length=20, choices=Role.choices, default=Role.USER,
    )

    class Meta:
        ordering = ('id',)
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    @property
    def is_admin(self) -> bool:
        """Проверить административную роль с учётом суперпользователя."""
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def is_moderator(self) -> bool:
        """Проверить роль модератора."""
        return self.role == self.Role.MODERATOR

    def __str__(self) -> str:
        """Вернуть краткое представление объекта."""
        return self.username
