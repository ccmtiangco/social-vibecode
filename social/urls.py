from django.urls import path

from . import views

app_name = 'social'

urlpatterns = [
    path('', views.feed, name='feed'),
    path('users/<str:username>/', views.profile, name='profile'),
    path('posts/new/', views.post_create, name='post_create'),
    path('users/<str:username>/follow/', views.follow_user, name='follow'),
    path('users/<str:username>/unfollow/', views.unfollow_user, name='unfollow'),
    path('posts/<int:post_id>/reshare/', views.reshare, name='reshare'),
]
