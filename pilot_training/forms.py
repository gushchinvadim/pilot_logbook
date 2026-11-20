
from django import forms

class ExcelUploadForm(forms.Form):
    file = forms.FileField(
        label="Загрузить Excel-файл (.xlsx)",
        help_text="Формат: .xlsx с листом 'Лист1' и колонками: NAME, SESSION_TITLE, EXERCISE_NAME и т.д."
    )






# from .models import Rating
#
# class RatingForm(forms.ModelForm):
#     class Meta:
#         model = Rating
#         fields = ['score', 'feedback']
#         widgets = {
#             'score': forms.RadioSelect(choices=[(2, '2'), (3, '3'), (4, '4'), (5, '5')]),
#             'feedback': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Замечания, рекомендации...'})
#         }
#         labels = {
#             'score': 'Оценка',
#             'feedback': 'Замечания'
#         }