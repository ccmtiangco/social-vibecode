from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Account type', {'fields': ('user_type',)}),
    )
    list_display = UserAdmin.list_display + ('user_type',)
    list_filter = UserAdmin.list_filter + ('user_type',)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            return (*fields, 'user_type')
        return fields
