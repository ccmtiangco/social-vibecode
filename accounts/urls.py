from django.urls import path

from .views import MemberLoginView, MemberLogoutView, RegistrationView

app_name = 'accounts'

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='register'),
    path('login/', MemberLoginView.as_view(), name='login'),
    path('logout/', MemberLogoutView.as_view(), name='logout'),
]
