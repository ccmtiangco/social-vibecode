from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(file, initial) for file in files]


class PostCreateForm(forms.Form):
    body = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 5, 'placeholder': 'What is on your mind?'}),
    )
    images = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
    )

    def clean_images(self):
        images = self.cleaned_data['images']
        if len(images) > 10:
            raise forms.ValidationError('A post can contain at most 10 images.')
        return images

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('body', '').strip() and not cleaned_data.get('images'):
            raise forms.ValidationError('Add text or at least one image.')
        return cleaned_data


class ReshareForm(forms.Form):
    body = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a comment (optional)'}),
    )
