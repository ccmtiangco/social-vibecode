from django.contrib import admin

from .models import AdCampaign, AdCreative, AdImpression, AdPurchase


@admin.register(AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'owner',
        'status',
        'starts_at',
        'ends_at',
        'funded_total_minor',
        'spent_total_minor',
    )
    list_filter = ('status', 'starts_at', 'ends_at')
    search_fields = ('name', 'owner__username')
    raw_id_fields = ('owner',)
    readonly_fields = (
        'funded_total_minor',
        'spent_total_minor',
        'created_at',
        'updated_at',
    )
    list_select_related = ('owner',)


@admin.register(AdCreative)
class AdCreativeAdmin(admin.ModelAdmin):
    list_display = ('headline', 'campaign', 'is_active', 'is_approved', 'updated_at')
    list_filter = ('is_active', 'is_approved', 'updated_at')
    search_fields = ('headline', 'body', 'campaign__name')
    raw_id_fields = ('campaign',)
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('campaign',)


@admin.register(AdPurchase)
class AdPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        'reference',
        'campaign',
        'purchaser',
        'amount_minor',
        'payment_method',
        'status',
        'created_at',
    )
    list_filter = ('payment_method', 'status', 'created_at')
    search_fields = ('campaign__name', 'purchaser__username')
    raw_id_fields = ('campaign', 'purchaser')
    readonly_fields = tuple(field.name for field in AdPurchase._meta.fields)
    list_select_related = ('campaign', 'purchaser')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdImpression)
class AdImpressionAdmin(admin.ModelAdmin):
    list_display = (
        'campaign',
        'creative',
        'viewer',
        'charged_amount_minor',
        'occurred_at',
    )
    list_filter = ('occurred_at',)
    search_fields = ('campaign__name', 'creative__headline', 'viewer__username')
    raw_id_fields = ('campaign', 'creative', 'viewer')
    readonly_fields = tuple(field.name for field in AdImpression._meta.fields)
    list_select_related = ('campaign', 'creative', 'viewer')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
