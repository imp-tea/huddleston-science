from django import forms

SCOPE_FIELDS = ("category", "subcategory", "topic", "q", "status")


class StartForm(forms.Form):
    mode = forms.ChoiceField(label="Mode", required=False,
        choices=[("recognition", "Multiple choice"), ("recall", "Recall · self-assessed")], initial="recognition")
    selection = forms.ChoiceField(label="Questions", required=False,
        choices=[("personalized", "Personalized mix"), ("random", "Random practice"), ("review", "Due reviews only")], initial="random")
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    category = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    subcategory = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    topic = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    q = forms.CharField(max_length=100, required=False, widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=[("", "All topics"), ("studied", "Studied"), ("unstudied", "Unstudied"), ("practiced", "Practiced")], required=False, widget=forms.HiddenInput)


class GoalForm(forms.Form):
    weekly_goal = forms.TypedChoiceField(label="Questions per week", coerce=int,
        choices=[(0, "Off"), (10, "10"), (20, "20"), (30, "30"), (50, "50"), (100, "100")])


class AnswerForm(forms.Form):
    selected = forms.TypedChoiceField(coerce=int, widget=forms.RadioSelect, label="Choose your answer")

    def __init__(self, choices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected"].choices = list(enumerate(choices))


class RecallForm(forms.Form):
    self_assessment = forms.TypedChoiceField(label="How did you do?", coerce=lambda value: value == "remembered",
        choices=[("remembered", "I remembered"), ("missed", "I need more practice")], widget=forms.RadioSelect)
