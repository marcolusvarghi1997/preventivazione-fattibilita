from django import forms

from .models import SiteConfiguration


class LanSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = ("lan_enabled",)
        labels = {"lan_enabled": "Consenti l'accesso dagli altri dispositivi della rete locale"}
        widgets = {"lan_enabled": forms.CheckboxInput(attrs={"class": "switch-input"})}
