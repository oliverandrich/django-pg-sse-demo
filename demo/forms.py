from django import forms

from demo.models import Message


class JoinForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "input w-full aria-invalid:input-error",
                    "autofocus": True,
                    "autocomplete": "nickname",
                    "placeholder": "Ada Lovelace",
                }
            ),
        }


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["text"]
        widgets = {
            "text": forms.TextInput(
                attrs={
                    "class": "input join-item w-full aria-invalid:input-error",
                    "autofocus": True,
                    "autocomplete": "off",
                    "placeholder": "Write a message…",
                    "aria-label": "Message",
                }
            ),
        }
