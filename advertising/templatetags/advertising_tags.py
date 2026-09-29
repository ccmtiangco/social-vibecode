from django import template

from accounts.models import User

register = template.Library()


@register.filter
def minor_units(value, currency_code='USD'):
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return ''
    return f'{currency_code} {amount // 100:,}.{amount % 100:02d}'


@register.filter
def can_manage_campaigns(user):
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    return user.user_type == User.UserType.AD_MANAGER or (
        user.is_staff and user.has_perm('advertising.change_adcampaign')
    )
