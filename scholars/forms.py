from django import forms


class StartForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    category = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    subcategory = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    topic = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)


class AnswerForm(forms.Form):
    selected = forms.TypedChoiceField(coerce=int, widget=forms.RadioSelect, label="Choose your answer")

    def __init__(self, choices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected"].choices = list(enumerate(choices))
