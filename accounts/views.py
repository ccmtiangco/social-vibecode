from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView

from .forms import MemberCreationForm


class RegistrationView(CreateView):
    form_class = MemberCreationForm
    template_name = 'registration/register.html'
    success_url = '/'


class MemberLoginView(LoginView):
    template_name = 'registration/login.html'
    next_page = '/'


class MemberLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:login')
