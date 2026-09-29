from django.urls import path

from . import views

app_name = 'advertising'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('campaigns/new/', views.campaign_create, name='campaign_create'),
    path('campaigns/<int:campaign_id>/edit/', views.campaign_edit, name='campaign_edit'),
    path('campaigns/<int:campaign_id>/status/', views.campaign_status, name='campaign_status'),
    path('campaigns/<int:campaign_id>/purchase/', views.campaign_purchase, name='campaign_purchase'),
    path('campaigns/<int:campaign_id>/creatives/new/', views.creative_create, name='creative_create'),
    path('creatives/<int:creative_id>/edit/', views.creative_edit, name='creative_edit'),
    path('creatives/<int:creative_id>/delete/', views.creative_delete, name='creative_delete'),
]
