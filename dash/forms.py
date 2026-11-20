from django import forms

from catalog.models import Category

INPUT = {'class': 'input'}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'parent', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={**INPUT, 'autofocus': True, 'maxlength': 80}),
            'parent': forms.Select(attrs={'class': 'select'}),
            'image': forms.ClearableFileInput(attrs={'class': 'input', 'accept': 'image/*'}),
            'is_active': forms.CheckboxInput(),
        }
        labels = {'parent': 'Parent category', 'image': 'Icon / image', 'is_active': 'Active (visible on the storefront)'}
        help_texts = {'parent': 'Leave empty to create a top-level category.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only top-level categories can be parents (two-level taxonomy).
        qs = Category.objects.filter(parent__isnull=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
            if self.instance.children.exists():
                self.fields['parent'].disabled = True
                self.fields['parent'].help_text = 'This category has subcategories, so it stays top-level.'
        self.fields['parent'].queryset = qs
        self.fields['parent'].empty_label = '— Top-level category —'
        self.fields['image'].required = False

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if not name:
            raise forms.ValidationError('Name is required.')
        return name

    def clean(self):
        cleaned = super().clean()
        name, parent = cleaned.get('name'), cleaned.get('parent')
        if name is not None:
            dup = Category.objects.filter(parent=parent, name__iexact=name)
            if self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error('name', 'A category with this name already exists here.')
        return cleaned
