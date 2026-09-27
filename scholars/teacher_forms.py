from django import forms


class QuestionContentForm(forms.Form):
    difficulty = forms.ChoiceField(required=False, choices=[("", "Not rated"), ("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")], help_text="Changing the question or answer clears its rating. Save the wording first, then assign a new difficulty.")
    question = forms.CharField(label='Question', max_length=10000, widget=forms.Textarea(attrs={'rows': 5}))
    correct_answer = forms.CharField(label='Correct answer', max_length=240,
        help_text='Use one canonical answer, as it should appear in autocomplete.')
    distractors = forms.CharField(label='Other choices', required=False,
        widget=forms.Textarea(attrs={'rows': 3}), help_text='Exactly three incorrect choices, one per line.')
    explanation = forms.CharField(label='Explanation', required=False, max_length=10000,
        widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, question_format='typed', **kwargs):
        super().__init__(*args, **kwargs)
        if question_format == 'typed':
            del self.fields['distractors']
            del self.fields['explanation']
        else:
            self.fields['distractors'].required = True
            self.fields['explanation'].required = True

    def clean(self):
        data = super().clean()
        if 'distractors' in self.fields and 'distractors' in data:
            choices = [line.strip() for line in data['distractors'].splitlines() if line.strip()]
            if len(choices) != 3 or any(len(choice) > 240 for choice in choices):
                self.add_error('distractors', 'Enter exactly three choices, each at most 240 characters.')
            elif len({choice.casefold() for choice in [data.get('correct_answer', ''), *choices]}) != 4:
                self.add_error('distractors', 'All four choices must be different.')
            else:
                data['distractors'] = choices
        return data


class QuestionEditForm(QuestionContentForm):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class QuestionCreateForm(QuestionContentForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class QuestionActionForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[('archive', 'Archive'), ('reactivate', 'Restore')], widget=forms.HiddenInput)
