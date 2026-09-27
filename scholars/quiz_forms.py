from django import forms

from .models import Category, Subcategory


class QuizCreateForm(forms.Form):
    name = forms.CharField(max_length=160, label='Quiz name')
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class QuizActionForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[(a, a) for a in
        ['rename', 'duplicate', 'archive', 'restore', 'remove', 'up', 'down', 'review']], widget=forms.HiddenInput)
    name = forms.CharField(max_length=160, required=False)
    request_key = forms.UUIDField(required=False, widget=forms.HiddenInput)
    item_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    revision_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)

    def clean(self):
        data = super().clean()
        action = data.get('action')
        if action in {'rename', 'duplicate'} and not data.get('name'):
            self.add_error('name', 'Enter a quiz name.')
        if action == 'duplicate' and not data.get('request_key'):
            self.add_error('request_key', 'Reload this page before duplicating.')
        if action in {'remove', 'up', 'down', 'review'} and not data.get('item_id'):
            self.add_error('item_id', 'Choose a question.')
        if action == 'review' and not data.get('revision_id'):
            self.add_error('revision_id', 'Reload to review the latest question.')
        return data


class RandomQuizForm(forms.Form):
    name = forms.CharField(max_length=160, label='Quiz name')
    categories = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple)
    subcategories = forms.MultipleChoiceField(required=False, widget=forms.SelectMultiple(attrs={'size': 8}),
        help_text='Optional: select specific subcategories. If selected, only questions in those subcategories are used. Leave empty to use all selected categories.')
    count = forms.IntegerField(min_value=1, max_value=100, initial=20, label='Number of questions')
    max_per_topic = forms.IntegerField(min_value=1, max_value=100, required=False,
                                       label='Maximum questions per topic', help_text='Leave empty for no topic limit.')
    distribution = forms.ChoiceField(choices=[('balanced', 'Balanced across categories'),
        ('pool', 'Sample across the whole selected pool')], initial='balanced')
    exclude_duplicates = forms.BooleanField(required=False, initial=True,
        label='Exclude matching prompts or answers', help_text='Uses the same duplicate grouping as Study quizzes.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categories'].choices = [(c.pk, c.pk) for c in Category.objects.filter(active=True).order_by('pk')]
        self.subs = list(Subcategory.objects.filter(active=True, category__active=True).order_by('category_id', 'id'))
        self.fields['subcategories'].choices = [(s.pk, f'{s.category_id} — {s.payload.get("label", s.pk)}') for s in self.subs]

    def clean(self):
        data = super().clean()
        for field in ['categories', 'subcategories']:
            if field in data:
                data[field] = list(dict.fromkeys(data[field]))
        selected = set(data.get('categories', []))
        if any(s.category_id not in selected for s in self.subs if s.pk in data.get('subcategories', [])):
            self.add_error('subcategories', 'Every selected subcategory must belong to a selected category.')
        return data
