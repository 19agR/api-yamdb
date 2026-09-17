from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from reviews.models import Category, Comment, Genre, Review, Title
from users.constants import EMAIL_MAX_LENGTH, USERNAME_MAX_LENGTH
from users.validators import username_validator, validate_username

from .exceptions import DuplicateReviewError

User = get_user_model()


class NormalizedEmailField(serializers.EmailField):
    """Проверить уникальность email после нормализации домена Django."""

    def to_internal_value(self, data: Any) -> str:
        """Привести домен к нижнему регистру до проверки валидаторов."""
        return User.objects.normalize_email(super().to_internal_value(data))


class NormalizedUsernameField(serializers.CharField):
    """Согласовать проверку имени с нормализацией UserManager."""

    def to_internal_value(self, data: Any) -> str:
        """Проверить исходные символы и нормализовать допустимое имя."""
        value = super().to_internal_value(data)
        username_validator(value)
        return User.normalize_username(value)


class SignupSerializer(serializers.Serializer):
    """Проверить данные регистрации и разрешить повторную выдачу кода."""

    username = NormalizedUsernameField(
        max_length=USERNAME_MAX_LENGTH,
        validators=[username_validator, validate_username],
    )
    email = NormalizedEmailField(max_length=EMAIL_MAX_LENGTH)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Проверить ограничения, зависящие от нескольких полей."""
        username, email = attrs['username'], attrs['email']
        errors = {}
        if User.objects.filter(username=username).exclude(
            email=email,
        ).exists():
            errors['username'] = ['Это имя пользователя уже занято.']
        if User.objects.filter(email=email).exclude(
            username=username,
        ).exists():
            errors['email'] = ['Эта электронная почта уже используется.']
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        """Создать объект из проверенных данных."""
        try:
            with transaction.atomic():
                user, _ = User.objects.get_or_create(
                    **validated_data,
                    defaults={'password': make_password(None)},
                )
        except IntegrityError:
            # A competing registration may reserve a field after validation.
            self.validate(validated_data)
            raise
        return user


class TokenSerializer(serializers.Serializer):
    """Проверить пользователя и срок действия кода подтверждения."""

    username = NormalizedUsernameField(
        max_length=USERNAME_MAX_LENGTH,
        validators=[username_validator, validate_username],
    )
    confirmation_code = serializers.CharField(write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Проверить ограничения, зависящие от нескольких полей."""
        user = get_object_or_404(User, username=attrs['username'])
        if not user.is_active or not default_token_generator.check_token(
            user, attrs['confirmation_code'],
        ):
            raise serializers.ValidationError({
                'confirmation_code': ['Недействительный код подтверждения.'],
            })
        attrs['user'] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """Представить и изменить пользователя с правами администратора."""

    username = NormalizedUsernameField(
        max_length=USERNAME_MAX_LENGTH,
        validators=[
            username_validator, validate_username,
            UniqueValidator(queryset=User.objects.all()),
        ],
    )
    email = NormalizedEmailField(
        max_length=EMAIL_MAX_LENGTH,
        validators=[UniqueValidator(queryset=User.objects.all())],
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name', 'bio', 'role',
        )

    def create(self, validated_data: dict[str, Any]) -> User:
        """Создать объект из проверенных данных."""
        return User.objects.create_user(**validated_data)


class ProfileSerializer(UserSerializer):
    """Изменить собственный профиль без повышения привилегий."""

    class Meta(UserSerializer.Meta):
        read_only_fields = ('role',)


class CategorySerializer(serializers.ModelSerializer):
    """Представить категорию через название и уникальный слаг."""

    class Meta:
        model = Category
        fields = ('name', 'slug')


class GenreSerializer(serializers.ModelSerializer):
    """Представить жанр через название и уникальный слаг."""

    class Meta:
        model = Genre
        fields = ('name', 'slug')


class TitleReadSerializer(serializers.ModelSerializer):
    """Представить произведение с рейтингом и справочниками."""

    category = CategorySerializer(read_only=True)
    genre = GenreSerializer(many=True, read_only=True)
    rating = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = Title
        fields = (
            'id', 'name', 'year', 'rating', 'description', 'genre', 'category',
        )


class TitleWriteSerializer(serializers.ModelSerializer):
    """Разрешить запись связей произведения по слагам."""

    category = serializers.SlugRelatedField(
        slug_field='slug', queryset=Category.objects.all(),
    )
    genre = serializers.SlugRelatedField(
        slug_field='slug', queryset=Genre.objects.all(),
        many=True, allow_empty=False,
    )

    class Meta:
        model = Title
        fields = ('id', 'name', 'year', 'description', 'genre', 'category')

    def to_representation(self, instance: Title) -> dict[str, Any]:
        """Вернуть публичное представление сохранённого произведения."""
        return TitleReadSerializer(instance, context=self.context).data


class ReviewSerializer(serializers.ModelSerializer):
    """Проверить оценку и единственность отзыва автора."""

    author = serializers.SlugRelatedField(
        slug_field='username', read_only=True,
    )

    class Meta:
        model = Review
        fields = ('id', 'text', 'author', 'score', 'pub_date')
        read_only_fields = ('pub_date',)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Проверить ограничения, зависящие от нескольких полей."""
        if self.instance is None and Review.objects.filter(
            title=self.context['title'], author=self.context['request'].user,
        ).exists():
            raise DuplicateReviewError
        return attrs


class CommentSerializer(serializers.ModelSerializer):
    """Представить комментарий с неизменяемым автором и датой."""

    author = serializers.SlugRelatedField(
        slug_field='username', read_only=True,
    )

    class Meta:
        model = Comment
        fields = ('id', 'text', 'author', 'pub_date')
        read_only_fields = ('pub_date',)
