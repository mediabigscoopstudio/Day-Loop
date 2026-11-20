from django import forms

from catalog.models import StockMovement

K = StockMovement.Kind


class StockUpdateForm(forms.Form):
    ACTIONS = [(K.ADD, 'Add stock'), (K.REMOVE, 'Remove stock'), (K.SET, 'Set exact count')]
    action = forms.ChoiceField(choices=ACTIONS, widget=forms.RadioSelect, initial=K.ADD)
    quantity = forms.IntegerField(min_value=0, max_value=1_000_000, widget=forms.NumberInput(attrs={'class': 'input', 'inputmode': 'numeric', 'min': 0}))
    reason = forms.CharField(max_length=160, widget=forms.TextInput(attrs={'class': 'input', 'placeholder': 'e.g. New batch received'}),
                             error_messages={'required': 'Please give a reason. It is kept in the stock history.'})

    def clean_reason(self):
        r = ' '.join(self.cleaned_data['reason'].split())
        if not r:
            raise forms.ValidationError('Please give a reason. It is kept in the stock history.')
        return r
