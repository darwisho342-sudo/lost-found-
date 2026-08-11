from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    AIAssistantSettings,
    AICapability,
    AICapabilitySetting,
    AdminCapabilityOverride,
    ContactRequest,
    Conversation,
    ItemReport,
    Message,
    UserProfile,
    normalize_phone_number,
    validate_phone_number,
)
from .moderation import SensitiveContentModerationService


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(
        required=False,
        max_length=30,
        help_text="Optional. You may include an international country code.",
    )
    consent_to_share_phone = forms.BooleanField(
        required=False,
        label="Allow active conversation contacts to see my phone number",
        help_text=(
            "Your number is never public. It is shown only to an active conversation "
            "participant, and you can revoke this permission at any time."
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "email",
            "phone_number",
            "consent_to_share_phone",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean_phone_number(self):
        raw_phone_number = self.cleaned_data.get("phone_number")
        validate_phone_number(raw_phone_number)
        return normalize_phone_number(raw_phone_number)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "phone_number": self.cleaned_data.get("phone_number", ""),
                    "consent_to_share_phone": self.cleaned_data.get(
                        "consent_to_share_phone", False
                    ),
                },
            )
        return user


class UserProfileForm(forms.ModelForm):
    phone_number = forms.CharField(
        required=False,
        max_length=30,
        help_text="Optional. You may include an international country code.",
    )

    class Meta:
        model = UserProfile
        fields = (
            "phone_number",
            "consent_to_share_phone",
            "mask_phone_number",
        )
        labels = {
            "consent_to_share_phone": "Allow active conversation contacts to see my phone number",
            "mask_phone_number": "Mask my phone number",
        }
        help_texts = {
            "phone_number": "Optional. You may include an international country code.",
            "consent_to_share_phone": (
                "Your number stays private unless an active private conversation exists. "
                "Turning this off hides it immediately."
            ),
            "mask_phone_number": (
                "Conversation contacts see only the final four digits. Administrators need "
                "a separate permission to review the full number."
            ),
        }

    def clean_phone_number(self):
        raw_phone_number = self.cleaned_data.get("phone_number")
        validate_phone_number(raw_phone_number)
        return normalize_phone_number(raw_phone_number)


class ContactRequestForm(forms.ModelForm):
    class Meta:
        model = ContactRequest
        fields = ("initial_message",)
        labels = {
            "initial_message": "Message to the report owner",
        }
        help_texts = {
            "initial_message": "This message appears immediately in your private conversation.",
        }
        widgets = {
            "initial_message": forms.Textarea(attrs={"rows": 5, "maxlength": 2000}),
        }

    def clean_initial_message(self):
        message = self.cleaned_data["initial_message"].strip()
        if not message:
            raise forms.ValidationError("Enter a private message.")
        return message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ("body",)
        labels = {"body": "Message"}
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 3, "maxlength": 2000, "placeholder": "Write a message…"}
            )
        }

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("A message cannot be empty.")
        return body


class ConversationDeactivateForm(forms.Form):
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 1000}),
        help_text="Required for administrator accountability. Message content is not copied here.",
    )

    def clean_reason(self):
        reason = SensitiveContentModerationService.clean(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError("Enter a deactivation reason.")
        return reason


class ConversationReopenForm(forms.Form):
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 1000}),
        help_text="Required for administrator accountability. It is not included in notifications.",
    )
    change_report_status = forms.BooleanField(
        required=False,
        label="Also change the related report back to Active",
    )

    def clean_reason(self):
        reason = SensitiveContentModerationService.clean(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError("Enter an administrator reason.")
        return reason


class ItemReportForm(forms.ModelForm):
    class Meta:
        model = ItemReport
        fields = (
            "title",
            "description",
            "category",
            "colour",
            "campus_location",
            "item_date",
            "image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "item_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_item_date(self):
        item_date = self.cleaned_data["item_date"]
        if item_date > timezone.localdate():
            raise forms.ValidationError("The date cannot be in the future.")
        return item_date

    def clean_colour(self):
        return " ".join(self.cleaned_data["colour"].split())


class ReportFilterForm(forms.Form):
    query = forms.CharField(required=False, label="Keyword")
    report_type = forms.ChoiceField(
        required=False, choices=[("", "All types"), *ItemReport.ReportType.choices]
    )
    category = forms.ChoiceField(
        required=False, choices=[("", "All categories"), *ItemReport.Category.choices]
    )
    colour = forms.CharField(required=False)
    campus_location = forms.ChoiceField(
        required=False,
        choices=[("", "All locations"), *ItemReport.CampusLocation.choices],
    )
    status = forms.ChoiceField(
        required=False, choices=[("", "All statuses"), *ItemReport.Status.choices]
    )


class AdminReportFilterForm(ReportFilterForm):
    visibility = forms.ChoiceField(
        required=False,
        choices=[("", "All visibility"), ("visible", "Visible"), ("hidden", "Hidden")],
    )


class AdminUserFilterForm(forms.Form):
    query = forms.CharField(required=False, label="Username or email")
    account_type = forms.ChoiceField(
        required=False,
        choices=[("", "All account types"), ("staff", "Staff"), ("regular", "Regular users")],
    )
    account_status = forms.ChoiceField(
        required=False,
        choices=[("", "All account statuses"), ("active", "Active"), ("inactive", "Inactive")],
    )


class AIAssistantRequestForm(forms.Form):
    capability = forms.ChoiceField(choices=(), label="Assistant capability")
    input_text = forms.CharField(
        required=False,
        label="Instructions or content",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": "Enter only the information needed for this advisory request.",
            }
        ),
    )
    reports = forms.ModelMultipleChoiceField(
        required=False,
        queryset=ItemReport.objects.none(),
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Hold Ctrl (Windows) or Command (Mac) to select multiple reports.",
    )
    conversation = forms.ModelChoiceField(
        required=False,
        queryset=Conversation.objects.none(),
        help_text="Conversation content is available only for the conversation-summary and risk-check tools.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .ai_assistant import AICapabilityService

        assistant_settings = AIAssistantSettings.get_solo()
        self.fields["input_text"].widget.attrs["maxlength"] = assistant_settings.maximum_input_length
        self.fields["capability"].choices = [
            (capability.code, capability.name)
            for capability in AICapabilityService.enabled_capabilities(user)
        ]
        self.fields["reports"].queryset = ItemReport.objects.filter(is_deleted=False).select_related("owner")
        self.fields["conversation"].queryset = Conversation.objects.select_related("item_report")

    def clean(self):
        cleaned_data = super().clean()
        capability = cleaned_data.get("capability")
        reports = list(cleaned_data.get("reports") or [])
        conversation = cleaned_data.get("conversation")
        input_text = cleaned_data.get("input_text", "").strip()
        if capability == "report_summarization" and not reports:
            self.add_error("reports", "Select at least one report.")
        elif capability == "conversation_summarization" and conversation is None:
            self.add_error("conversation", "Select a conversation.")
        elif capability == "matching_insights" and len(reports) != 2:
            self.add_error("reports", "Select exactly two reports.")
        elif capability in ("data_extraction", "content_generation") and not input_text:
            self.add_error("input_text", "Enter content for this capability.")
        elif capability == "risk_violation_checks" and not (input_text or reports or conversation):
            self.add_error(None, "Enter text or select content to check.")
        return cleaned_data


class AIAssistantSettingsForm(forms.ModelForm):
    enabled_capabilities = forms.ModelMultipleChoiceField(
        queryset=AICapability.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AIAssistantSettings
        fields = (
            "is_enabled",
            "provider_name",
            "model_name",
            "request_timeout_seconds",
            "maximum_input_length",
        )
        labels = {"is_enabled": "Enable AI Assistant"}
        help_texts = {
            "provider_name": "Safe display name only. API keys must come from environment variables.",
            "model_name": "Configuration label only; the initial provider is local and deterministic.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enabled_capabilities"].queryset = AICapability.objects.filter(is_available=True)
        self.fields["enabled_capabilities"].initial = AICapability.objects.filter(
            global_setting__is_enabled=True
        )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_enabled") and not cleaned_data.get("enabled_capabilities"):
            self.add_error("enabled_capabilities", "Enable at least one capability while the assistant is enabled.")
        timeout = cleaned_data.get("request_timeout_seconds")
        if timeout is not None and not 1 <= timeout <= 120:
            self.add_error("request_timeout_seconds", "Use a timeout between 1 and 120 seconds.")
        maximum = cleaned_data.get("maximum_input_length")
        if maximum is not None and not 100 <= maximum <= 20000:
            self.add_error("maximum_input_length", "Use an input limit between 100 and 20,000 characters.")
        return cleaned_data


class AdminCapabilityOverrideForm(forms.Form):
    capability = forms.ModelChoiceField(queryset=AICapability.objects.none())
    setting = forms.ChoiceField(choices=AdminCapabilityOverride.OverrideSetting.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["capability"].queryset = AICapability.objects.filter(is_available=True)
