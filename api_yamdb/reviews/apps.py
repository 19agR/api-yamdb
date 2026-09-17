from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    """Настроить приложение произведений и отзывов."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reviews'
    verbose_name = 'Произведения и отзывы'
