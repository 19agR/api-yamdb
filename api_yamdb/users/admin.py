from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Добавить профиль и роль в стандартную админку пользователей."""

    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = (*BaseUserAdmin.list_filter, 'role')
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        ('YaMDb', {'fields': ('bio', 'role')}),
    )
    add_fieldsets = (
        *BaseUserAdmin.add_fieldsets,
        ('YaMDb', {'fields': ('email', 'bio', 'role')}),
    )
