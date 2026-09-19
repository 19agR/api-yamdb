from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .constants import (
    MAX_SCORE, MIN_SCORE, NAME_MAX_LENGTH, SLUG_MAX_LENGTH,
    TEXT_PREVIEW_LENGTH,
)
from .validators import validate_year


class NameSlugModel(models.Model):
    """Хранить общие поля и порядок объектов справочника."""

    name = models.CharField('Название', max_length=NAME_MAX_LENGTH)
    slug = models.SlugField('Слаг', max_length=SLUG_MAX_LENGTH, unique=True)

    class Meta:
        abstract = True
        ordering = ('name',)

    def __str__(self) -> str:
        """Вернуть краткое представление объекта."""
        return self.name[:TEXT_PREVIEW_LENGTH]


class Category(NameSlugModel):
    """Классифицировать произведения по типу."""

    class Meta(NameSlugModel.Meta):
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'


class Genre(NameSlugModel):
    """Хранить предустановленный жанр произведений."""

    class Meta(NameSlugModel.Meta):
        verbose_name = 'Жанр'
        verbose_name_plural = 'Жанры'


class Title(models.Model):
    """Хранить описание произведения без самого медиаконтента."""

    name = models.CharField(
        'Название', max_length=NAME_MAX_LENGTH, db_index=True,
    )
    year = models.PositiveSmallIntegerField(
        'Год выпуска', validators=[validate_year], db_index=True,
    )
    description = models.TextField('Описание', blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True,
        related_name='titles', verbose_name='Категория',
    )
    genre = models.ManyToManyField(
        Genre, through='GenreTitle', related_name='titles',
        verbose_name='Жанры',
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'Произведение'
        verbose_name_plural = 'Произведения'

    def __str__(self) -> str:
        """Вернуть краткое представление объекта."""
        return self.name[:TEXT_PREVIEW_LENGTH]


class GenreTitle(models.Model):
    """Хранить уникальную связь произведения с жанром."""

    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('title', 'genre'), name='unique_title_genre',
            ),
        ]
        verbose_name = 'Жанр произведения'
        verbose_name_plural = 'Жанры произведений'

    def __str__(self) -> str:
        """Вернуть краткое представление объекта."""
        return f'{self.title}: {self.genre}'[:TEXT_PREVIEW_LENGTH]


class Publication(models.Model):
    """Хранить текст, автора и дату отзыва или комментария."""

    text = models.TextField('Текст')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='%(class)ss', verbose_name='Автор',
    )
    pub_date = models.DateTimeField(
        'Дата публикации', default=timezone.now, editable=False, db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ('-pub_date',)

    def __str__(self) -> str:
        """Вернуть краткое представление объекта."""
        return self.text[:TEXT_PREVIEW_LENGTH]


class Review(Publication):
    """Хранить единственный отзыв автора и оценку произведения."""

    title = models.ForeignKey(
        Title, on_delete=models.CASCADE, related_name='reviews',
        verbose_name='Произведение',
    )
    score = models.PositiveSmallIntegerField(
        'Оценка',
        validators=[
            MinValueValidator(MIN_SCORE), MaxValueValidator(MAX_SCORE),
        ],
    )

    class Meta(Publication.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=('title', 'author'), name='unique_author_title_review',
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=MIN_SCORE, score__lte=MAX_SCORE),
                name='review_score_between_1_and_10',
            ),
        ]
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'


class Comment(Publication):
    """Хранить комментарий пользователя к отзыву."""

    review = models.ForeignKey(
        Review, on_delete=models.CASCADE, related_name='comments',
        verbose_name='Отзыв',
    )

    class Meta(Publication.Meta):
        verbose_name = 'Комментарий'
        verbose_name_plural = 'Комментарии'
