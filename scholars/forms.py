from django import forms

SCOPE_FIELDS = ("category", "subcategory", "topic", "q", "status")


class StartForm(forms.Form):
    mode = forms.ChoiceField(label="Mode", required=False,
        choices=[("typed", "Typed answers"), ("recognition", "Multiple choice"), ("recall", "Recall · self-assessed")], initial="typed")
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


class TypedAnswerForm(forms.Form):
    typed_answer = forms.CharField(label="Your answer", max_length=240, required=False, strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "off",
                                      "aria-describedby": "answer-help answer-status", "autofocus": True}))
    action = forms.ChoiceField(choices=[("answer", "Answer"), ("skip", "Skip")], required=False)

    def clean(self):
        data = super().clean()
        if data.get("action") != "skip" and not data.get("typed_answer", "").strip():
            self.add_error("typed_answer", "Enter an answer or skip this question.")
        return data


class InterestsForm(forms.Form):
    categories = forms.MultipleChoiceField(label="Study categories", widget=forms.CheckboxSelectMultiple,
                                           error_messages={"required": "Select at least one category."})

    def __init__(self, *args, **kwargs):
        from .models import Category
        super().__init__(*args, **kwargs)
        self.fields["categories"].choices = [(c.pk, c.pk) for c in Category.objects.filter(active=True).order_by("pk")]


class StudyStartForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    subcategory = forms.CharField(max_length=100, widget=forms.HiddenInput)


class ReadingMoveForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    direction = forms.ChoiceField(choices=[("back", "Back"), ("next", "Next")])


class StudyAnswerForm(forms.Form):
    typed_answer = forms.CharField(label="Your answer", max_length=240, required=False, strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "off", "aria-describedby": "answer-help answer-status", "autofocus": True}))
    action = forms.ChoiceField(choices=[("answer", "Answer"), ("skip", "Skip")])

    def clean(self):
        data = super().clean()
        if data.get("action") != "skip" and not data.get("typed_answer", "").strip():
            self.add_error("typed_answer", "Enter an answer or skip this question.")
        return data
