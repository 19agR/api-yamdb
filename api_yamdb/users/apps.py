from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Настроить приложение пользователей."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    verbose_name = 'Пользователи'
