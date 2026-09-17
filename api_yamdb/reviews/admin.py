from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Category, Comment, Genre, GenreTitle, Review, Title


@admin.register(Category, Genre)
class NameSlugAdmin(admin.ModelAdmin):
    """Настроить поиск и редактирование справочников."""

    list_display = ('name', 'slug')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class GenreTitleInline(admin.TabularInline):
    """Редактировать жанры произведения без лишних запросов."""

    model = GenreTitle
    extra = 1
    autocomplete_fields = ('genre',)

    def get_queryset(self, request: HttpRequest) -> QuerySet[GenreTitle]:
        """Загрузить объекты и используемые связанные данные."""
        return super().get_queryset(request).select_related('title', 'genre')


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    """Настроить фильтры и жанры в админке произведений."""

    list_display = ('name', 'year', 'category')
    list_filter = ('category', 'genre', 'year')
    search_fields = ('name',)
    list_select_related = ('category',)
    autocomplete_fields = ('category',)
    inlines = (GenreTitleInline,)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Настроить поиск и фильтры отзывов."""

    list_display = ('id', 'title', 'author', 'score', 'pub_date')
    list_filter = ('score', 'pub_date')
    search_fields = ('text', 'title__name', 'author__username')
    autocomplete_fields = ('title', 'author')
    list_select_related = ('title', 'author')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """Настроить поиск и фильтры комментариев."""

    list_display = ('id', 'review', 'author', 'pub_date')
    list_filter = ('pub_date',)
    search_fields = ('text', 'author__username')
    autocomplete_fields = ('review', 'author')
    list_select_related = ('review', 'author')
