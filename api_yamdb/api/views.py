from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Avg, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from reviews.models import Category, Comment, Genre, Review, Title

from .exceptions import DuplicateReviewError
from .filters import TitleFilter
from .permissions import (
    IsAdmin, IsAdminOrReadOnly, IsAuthorModeratorAdminOrReadOnly,
)
from .serializers import (
    CategorySerializer, CommentSerializer, GenreSerializer, ProfileSerializer,
    ReviewSerializer, SignupSerializer, TitleReadSerializer,
    TitleWriteSerializer, TokenSerializer, UserSerializer,
)
from .services import send_confirmation_code

User = get_user_model()


class SignupView(APIView):
    """Зарегистрировать пользователя и отправить код подтверждения."""

    permission_classes = (permissions.AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        """Обработать проверенные данные запроса и вернуть ответ API."""
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_confirmation_code(user)
        return Response(serializer.data)


class TokenView(APIView):
    """Обменять действительный код подтверждения на JWT."""

    permission_classes = (permissions.AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        """Обработать проверенные данные запроса и вернуть ответ API."""
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = AccessToken.for_user(serializer.validated_data['user'])
        return Response({'token': str(token)})


class PartialUpdateModelViewSet(viewsets.ModelViewSet):
    """Ограничить изменение объектов методом PATCH согласно ТЗ."""

    http_method_names = ('get', 'post', 'patch', 'delete', 'head', 'options')


class UserViewSet(PartialUpdateModelViewSet):
    """Предоставить управление пользователями и собственным профилем."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (IsAdmin,)
    lookup_field = 'username'
    lookup_value_regex = r'[\w.@+-]+'
    filter_backends = (filters.SearchFilter,)
    search_fields = ('username',)

    @action(
        detail=False, methods=('get', 'patch'),
        permission_classes=(permissions.IsAuthenticated,),
        serializer_class=ProfileSerializer,
    )
    def me(self, request: Request) -> Response:
        """Прочитать или частично изменить собственный профиль."""
        if request.method == 'PATCH':
            serializer = self.get_serializer(
                request.user, data=request.data, partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class ListCreateDestroyViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin,
    mixins.DestroyModelMixin, viewsets.GenericViewSet,
):
    """Предоставить разрешённые операции со справочниками."""

    permission_classes = (IsAdminOrReadOnly,)
    lookup_field = 'slug'
    filter_backends = (filters.SearchFilter,)
    search_fields = ('name',)


class CategoryViewSet(ListCreateDestroyViewSet):
    """Предоставить категории с поиском по названию."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class GenreViewSet(ListCreateDestroyViewSet):
    """Предоставить жанры с поиском по названию."""

    queryset = Genre.objects.all()
    serializer_class = GenreSerializer


class TitleViewSet(PartialUpdateModelViewSet):
    """Предоставить произведения с рейтингом и фильтрами."""

    queryset = Title.objects.select_related('category').prefetch_related(
        'genre',
    ).annotate(rating=Avg('reviews__score')).order_by('id')
    permission_classes = (IsAdminOrReadOnly,)
    filter_backends = (DjangoFilterBackend,)
    filterset_class = TitleFilter

    def get_serializer_class(
        self,
    ) -> type[TitleReadSerializer | TitleWriteSerializer]:
        """Выбрать представление для чтения или записи произведения."""
        if self.action in ('list', 'retrieve'):
            return TitleReadSerializer
        return TitleWriteSerializer


class ReviewViewSet(PartialUpdateModelViewSet):
    """Ограничить операции отзывами выбранного произведения."""

    serializer_class = ReviewSerializer
    permission_classes = (IsAuthorModeratorAdminOrReadOnly,)

    @cached_property
    def title(self) -> Title:
        """Найти родительское произведение или вернуть 404."""
        return get_object_or_404(Title, pk=self.kwargs['title_id'])

    def get_queryset(self) -> QuerySet[Review]:
        """Загрузить объекты и используемые связанные данные."""
        return self.title.reviews.select_related('author')

    def get_serializer_context(self) -> dict[str, Any]:
        """Передать сериализатору проверенного родителя."""
        return {**super().get_serializer_context(), 'title': self.title}

    def perform_create(self, serializer: ReviewSerializer) -> None:
        """Сохранить публикацию с автором и родительским объектом."""
        try:
            with transaction.atomic():
                serializer.save(author=self.request.user, title=self.title)
        except IntegrityError as error:
            if self.title.reviews.filter(author=self.request.user).exists():
                raise DuplicateReviewError from error
            raise


class CommentViewSet(PartialUpdateModelViewSet):
    """Ограничить комментарии отзывом выбранного произведения."""

    serializer_class = CommentSerializer
    permission_classes = (IsAuthorModeratorAdminOrReadOnly,)

    @cached_property
    def review(self) -> Review:
        """Найти отзыв в указанном произведении или вернуть 404."""
        return get_object_or_404(
            Review, pk=self.kwargs['review_id'],
            title_id=self.kwargs['title_id'],
        )

    def get_queryset(self) -> QuerySet[Comment]:
        """Загрузить объекты и используемые связанные данные."""
        return self.review.comments.select_related('author')

    def get_serializer_context(self) -> dict[str, Any]:
        # Resolve the parent for POST too, before validating the request body.
        """Передать сериализатору проверенного родителя."""
        return {**super().get_serializer_context(), 'review': self.review}

    def perform_create(self, serializer: CommentSerializer) -> None:
        """Сохранить публикацию с автором и родительским объектом."""
        serializer.save(author=self.request.user, review=self.review)
