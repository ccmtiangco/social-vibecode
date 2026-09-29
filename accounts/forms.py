from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm

from .models import User


class MemberCreationForm(BaseUserCreationForm):
    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ('username',)
