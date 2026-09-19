from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from reviews.models import Publication


class IsAdmin(BasePermission):
    """Разрешить доступ администратору или суперпользователю."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Проверить права на операцию над ресурсом."""
        return request.user.is_authenticated and request.user.is_admin


class IsAdminOrReadOnly(IsAdmin):
    """Разрешить публичное чтение и запись администратору."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Проверить права на операцию над ресурсом."""
        return (
            request.method in SAFE_METHODS
            or super().has_permission(request, view)
        )


class IsAuthorModeratorAdminOrReadOnly(BasePermission):
    """Проверить право на изменение пользовательской публикации."""

    def has_object_permission(
        self, request: Request, view: APIView, obj: Publication,
    ) -> bool:
        """Проверить права на чтение или изменение публикации."""
        return (
            request.method in SAFE_METHODS
            or obj.author_id == request.user.pk
            or request.user.is_admin
            or request.user.is_moderator
        )
