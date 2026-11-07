
from django import forms


class FurnitureLibraryImportForm(forms.Form):
    dxf_file = forms.FileField(
        label='DXF-файл библиотеки мебели',
        help_text='Выбери файл с определениями блоков мебели.',
    )

    def clean_dxf_file(self):
        file = self.cleaned_data['dxf_file']

        if not file.name.lower().endswith('.dxf'):
            raise forms.ValidationError(
                'Необходимо загрузить файл DXF.'
            )

        return file
