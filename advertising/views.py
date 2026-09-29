from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AdCreativeForm, CampaignForm, SimulatedPurchaseForm
from .models import AdCampaign, AdCreative, AdImpression, AdPurchase
from .services import (
    purchase_campaign,
    require_campaign_access,
    transition_campaign_status,
)


def _is_ad_manager(user):
    return user.user_type == get_user_model().UserType.AD_MANAGER


def _campaigns_for_dashboard(user):
    if not user.is_active:
        raise PermissionDenied
    if user.is_staff and user.has_perm('advertising.change_adcampaign'):
        return AdCampaign.objects.all()
    if _is_ad_manager(user):
        return AdCampaign.objects.filter(owner=user)
    raise PermissionDenied


def _managed_campaign(user, campaign_id):
    campaign = get_object_or_404(
        AdCampaign.objects.select_related('owner'),
        pk=campaign_id,
    )
    require_campaign_access(user, campaign)
    return campaign


@login_required
def dashboard(request):
    campaigns = (
        _campaigns_for_dashboard(request.user)
        .select_related('owner')
        .prefetch_related(
            'creatives',
            Prefetch(
                'purchases',
                queryset=AdPurchase.objects.order_by('-created_at')[:5],
                to_attr='recent_purchases',
            ),
            Prefetch(
                'impressions',
                queryset=AdImpression.objects.order_by('-occurred_at')[:5],
                to_attr='recent_impressions',
            ),
        )
        .order_by('-created_at')
    )
    return render(
        request,
        'advertising/dashboard.html',
        {
            'campaigns': campaigns,
            'can_create_campaign': _is_ad_manager(request.user),
        },
    )


@login_required
def campaign_create(request):
    if not request.user.is_active or not _is_ad_manager(request.user):
        raise PermissionDenied
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.owner = request.user
            try:
                campaign.full_clean()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                campaign.save()
                messages.success(request, 'Campaign created. Add a creative to continue.')
                return redirect('advertising:dashboard')
    else:
        form = CampaignForm()
    return render(
        request,
        'advertising/campaign_form.html',
        {'form': form, 'heading': 'Start a campaign'},
    )


@login_required
def campaign_edit(request, campaign_id):
    campaign = _managed_campaign(request.user, campaign_id)
    if request.method == 'POST':
        form = CampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            messages.success(request, 'Campaign details updated.')
            return redirect('advertising:dashboard')
    else:
        form = CampaignForm(instance=campaign)
    return render(
        request,
        'advertising/campaign_form.html',
        {'form': form, 'heading': 'Edit campaign', 'campaign': campaign},
    )


@login_required
@require_POST
def campaign_status(request, campaign_id):
    campaign = _managed_campaign(request.user, campaign_id)
    try:
        transition_campaign_status(
            actor=request.user,
            campaign_id=campaign.pk,
            status=request.POST.get('status'),
        )
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, 'Campaign status updated.')
    return redirect('advertising:dashboard')


@login_required
@require_POST
def campaign_purchase(request, campaign_id):
    campaign = _managed_campaign(request.user, campaign_id)
    form = SimulatedPurchaseForm(request.POST)
    if form.is_valid():
        amount = form.cleaned_data['amount_minor']
        try:
            purchase = purchase_campaign(
                actor=request.user,
                campaign_id=campaign.pk,
                amount_minor=amount,
            )
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        else:
            messages.success(
                request,
                f'Simulated funding added: {purchase.amount_minor:,} '
                f'{campaign.currency_code} minor units. No payment was processed.',
            )
    else:
        messages.error(request, 'Enter a valid simulated funding amount.')
    return redirect('advertising:dashboard')


@login_required
def creative_create(request, campaign_id):
    campaign = _managed_campaign(request.user, campaign_id)
    if request.method == 'POST':
        form = AdCreativeForm(request.POST, request.FILES)
        if form.is_valid():
            creative = form.save(commit=False)
            creative.campaign = campaign
            try:
                creative.full_clean()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                creative.save()
                messages.success(request, 'Creative saved. It awaits staff approval.')
                return redirect('advertising:dashboard')
    else:
        form = AdCreativeForm()
    return render(
        request,
        'advertising/creative_form.html',
        {'form': form, 'campaign': campaign, 'heading': 'Add a creative'},
    )


@login_required
def creative_edit(request, creative_id):
    creative = get_object_or_404(
        AdCreative.objects.select_related('campaign', 'campaign__owner'),
        pk=creative_id,
    )
    require_campaign_access(request.user, creative.campaign)
    if request.method == 'POST':
        form = AdCreativeForm(request.POST, request.FILES, instance=creative)
        if form.is_valid():
            form.save()
            messages.success(request, 'Creative updated.')
            return redirect('advertising:dashboard')
    else:
        form = AdCreativeForm(instance=creative)
    return render(
        request,
        'advertising/creative_form.html',
        {'form': form, 'campaign': creative.campaign, 'heading': 'Edit creative'},
    )


@login_required
@require_POST
def creative_delete(request, creative_id):
    creative = get_object_or_404(
        AdCreative.objects.select_related('campaign', 'campaign__owner'),
        pk=creative_id,
    )
    require_campaign_access(request.user, creative.campaign)
    try:
        creative.delete()
    except ProtectedError:
        messages.error(request, 'A creative with recorded impressions cannot be deleted.')
    else:
        messages.success(request, 'Creative deleted.')
    return redirect('advertising:dashboard')
