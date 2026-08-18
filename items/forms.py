from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile
from PIL import Image, UnidentifiedImageError

from .choices import (
    ALL_ITEM_TYPE_CHOICES, BRAND_CHOICES, COLOUR_CHOICES, CONDITION_CHOICES,
    COUNTRY_CHOICES, ITEM_TYPE_CHOICES, MATERIAL_CHOICES, PATTERN_CHOICES, SIZE_CHOICES,
    VERIFICATION_QUESTION_TYPES, PLACE_TYPE_CHOICES, RETURN_METHOD_CHOICES, RETURN_STATUS_CHOICES,
)
from .models import (
    ClaimAppeal,
    ContentReport,
    ContactRequest,
    ClaimEvidence,
    Conversation,
    CustodyRecord,
    ItemReport,
    Message,
    ReportImage,
    ReturnArrangement,
    SavedSearch,
    UserProfile,
    UniversityLocation,
    normalize_phone_number,
    validate_evidence_size,
    validate_evidence_content,
    validate_phone_number,
)
from .moderation import SensitiveContentModerationService
from .university import UniversityAccessService


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(
        required=False,
        max_length=30,
        help_text=_("Optional. You may include an international country code."),
    )
    consent_to_share_phone = forms.BooleanField(
        required=False,
        label=_("Allow active conversation contacts to see my phone number"),
        help_text=(
            _("Your number is never public. It is shown only to an active conversation participant, and you can revoke this permission at any time.")
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
            raise forms.ValidationError(_("An account already uses this email address."))
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
                    "university_eligible": UniversityAccessService.email_is_eligible(user.email),
                    "preferred_scope": (
                        ItemReport.Scope.UNIVERSITY
                        if UniversityAccessService.email_is_eligible(user.email)
                        else ItemReport.Scope.INTERNATIONAL
                    ),
                },
            )
        return user


class UserProfileForm(forms.ModelForm):
    phone_number = forms.CharField(
        required=False,
        max_length=30,
        help_text=_("Optional. You may include an international country code."),
    )

    class Meta:
        model = UserProfile
        fields = (
            "display_name", "preferred_language", "preferred_scope", "phone_number",
            "consent_to_share_phone",
            "mask_phone_number",
            "notify_strong_matches", "notify_claim_updates", "notify_messages", "email_notifications",
        )
        labels = {
            "consent_to_share_phone": _("Allow active conversation contacts to see my phone number"),
            "mask_phone_number": _("Mask my phone number"),
        }
        help_texts = {
            "phone_number": _("Optional. You may include an international country code."),
            "consent_to_share_phone": (
                _("Your number stays private unless an active private conversation exists. Turning this off hides it immediately.")
            ),
            "mask_phone_number": (
                _("Conversation contacts see only the final four digits. Administrators need a separate permission to review the full number.")
            ),
        }

    def clean_phone_number(self):
        raw_phone_number = self.cleaned_data.get("phone_number")
        validate_phone_number(raw_phone_number)
        return normalize_phone_number(raw_phone_number)

    def clean_preferred_scope(self):
        scope = self.cleaned_data.get("preferred_scope") or self.instance.preferred_scope
        if scope == ItemReport.Scope.UNIVERSITY and not UniversityAccessService.is_verified(self.instance.user):
            raise forms.ValidationError(_("Your verified account has International access only."))
        return scope

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_language"].required = False
        self.fields["preferred_scope"].required = False


class ContactRequestForm(forms.ModelForm):
    class Meta:
        model = ContactRequest
        fields = ("initial_message",)
        labels = {
            "initial_message": _("Message to the report owner"),
        }
        help_texts = {
            "initial_message": _("This message appears immediately in your private conversation."),
        }
        widgets = {
            "initial_message": forms.Textarea(attrs={"rows": 5, "maxlength": 2000}),
        }

    def clean_initial_message(self):
        message = self.cleaned_data["initial_message"].strip()
        if not message:
            raise forms.ValidationError(_("Enter a private message."))
        return message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ("body", "attachment")
        labels = {"body": _("Message")}
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 3, "maxlength": 2000, "placeholder": _("Write a message…")}
            )
        }

    def clean_attachment(self):
        upload = self.cleaned_data.get("attachment")
        if upload:
            validate_evidence_size(upload)
            validate_evidence_content(upload)
            FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf"))(upload)
        return upload

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError(_("A message cannot be empty."))
        return body


class ConversationDeactivateForm(forms.Form):
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 1000}),
        help_text=_("Required for administrator accountability. Message content is not copied here."),
    )

    def clean_reason(self):
        reason = SensitiveContentModerationService.clean(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError(_("Enter a deactivation reason."))
        return reason


class ConversationReopenForm(forms.Form):
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4, "maxlength": 1000}),
        help_text=_("Required for administrator accountability. It is not included in notifications."),
    )
    change_report_status = forms.BooleanField(
        required=False,
        label=_("Also change the related report back to Active"),
    )

    def clean_reason(self):
        reason = SensitiveContentModerationService.clean(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError(_("Enter an administrator reason."))
        return reason


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        items = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(item, initial) for item in items]


def prepare_report_image(upload):
    """Validate real image bytes, resize locally, and strip embedded metadata."""
    if not upload or not isinstance(upload, UploadedFile):
        return upload
    try:
        upload.seek(0)
        with Image.open(upload) as source:
            source.verify()
        upload.seek(0)
        with Image.open(upload) as source:
            if source.width < 1 or source.height < 1 or source.width > 12000 or source.height > 12000:
                raise forms.ValidationError(_("Use an image no larger than 12,000×12,000 pixels."))
            image = source.convert("RGB") if source.mode not in ("RGB", "RGBA") else source.copy()
            image.thumbnail((2400, 2400))
            output = BytesIO()
            suffix = Path(upload.name).suffix.lower()
            image_format = "PNG" if suffix == ".png" else "WEBP" if suffix == ".webp" else "JPEG"
            if image_format == "JPEG" and image.mode != "RGB":
                image = image.convert("RGB")
            image.save(output, format=image_format, quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError):
        raise forms.ValidationError(_("Upload a genuine JPG, PNG, or WebP image."))
    output.seek(0)
    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image_format]
    return InMemoryUploadedFile(
        output, "ImageField", f"report-{uuid4().hex}{extension}",
        f"image/{image_format.lower()}", output.getbuffer().nbytes, None,
    )


class ItemReportForm(forms.ModelForm):
    country = forms.ChoiceField(required=False, choices=(("", _("Select a country")), *COUNTRY_CHOICES))
    additional_images = MultipleImageField(
        required=False,
        help_text=_("Optional. Add up to two more images, for three images total."),
    )
    verification_question_1_type = forms.ChoiceField(required=False, choices=(("", _("Select a question")), *VERIFICATION_QUESTION_TYPES))
    verification_question_1_text = forms.CharField(required=False, max_length=240)
    verification_question_1_answer = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2, "dir": "auto"}))
    verification_question_2_type = forms.ChoiceField(required=False, choices=(("", _("Select a question")), *VERIFICATION_QUESTION_TYPES))
    verification_question_2_text = forms.CharField(required=False, max_length=240)
    verification_question_2_answer = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2, "dir": "auto"}))
    verification_question_3_type = forms.ChoiceField(required=False, choices=(("", _("Select a question")), *VERIFICATION_QUESTION_TYPES))
    verification_question_3_text = forms.CharField(required=False, max_length=240)
    verification_question_3_answer = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2, "dir": "auto"}))

    class Meta:
        model = ItemReport
        fields = (
            "title",
            "category",
            "item_type", "custom_item_type", "primary_colour", "secondary_colour",
            "material", "approximate_size", "pattern", "item_condition",
            "brand", "custom_brand", "model",
            "campus_location",
            "university_location",
            "custom_location",
            "country", "region", "city", "district", "place_type", "place_name",
            "public_location", "exact_private_location",
            "item_date",
            "additional_details",
            "image", "duplicate_confirmed",
            "require_official_handover",
        )
        widgets = {
            "item_date": forms.DateInput(attrs={"type": "date"}),
            "additional_details": forms.Textarea(attrs={"rows": 5, "maxlength": 1000, "dir": "auto"}),
            "exact_private_location": forms.Textarea(attrs={"rows": 3, "maxlength": 500, "dir": "auto"}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001"}),
        }

    def __init__(self, *args, report_type=None, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_type = report_type or getattr(self.instance, "report_type", "")
        self.scope = scope or getattr(self.instance, "scope", ItemReport.Scope.UNIVERSITY)
        self.instance.scope = self.scope
        self.fields["category"].choices = (("", _("Select a category")), *ItemReport.Category.choices)
        self.fields["title"].required = False
        self.fields["item_type"].choices = (("", _("Select an item type")), *ALL_ITEM_TYPE_CHOICES)
        self.fields["primary_colour"].required = not bool(self.data.get("colour"))
        self.fields["primary_colour"].choices = (("", _("Select a primary colour")), *COLOUR_CHOICES)
        for field_name in ("secondary_colour", "material", "approximate_size", "pattern", "item_condition", "brand"):
            self.fields[field_name].choices = (("", _("Not specified")), *self.fields[field_name].choices)
        self.fields["campus_location"].choices = (("", _("Select a general location")), *ItemReport.CampusLocation.choices)
        self.fields["campus_location"].required = False
        self.fields["university_location"].queryset = self.fields["university_location"].queryset.filter(is_active=True)
        self.fields["university_location"].required = False
        self.fields["university_location"].label = _("Campus, building, and general area")
        submitted_country = self.data.get("country") if self.is_bound else ""
        legacy_country = self.instance.country if self.instance.pk else submitted_country
        if legacy_country and legacy_country not in dict(COUNTRY_CHOICES):
            self.fields["country"].choices = (
                ("", _("Select a country")), (legacy_country, legacy_country), *COUNTRY_CHOICES
            )
        self.fields["place_type"].choices = (("", _("Select a place type")), *PLACE_TYPE_CHOICES)
        self.fields["exact_private_location"].help_text = _(
            "Strictly private. Never used in matching, search, notifications, analytics, or public pages."
        )
        legacy_post = bool(self.data.get("colour"))
        self.fields["duplicate_confirmed"].widget = forms.HiddenInput()
        self.fields["item_date"].label = _("Date found") if self.report_type == ItemReport.ReportType.FOUND else _("Date lost")
        self.fields["approximate_size"].help_text = _("Choose the closest approximate size.")
        self.fields["additional_details"].help_text = _("Do not include passwords, complete card numbers, identification numbers, security codes, phone numbers, addresses, or other private information.")
        self.fields["image"].help_text = _("Maximum 5 MB. Do not upload images showing private numbers, PINs, addresses, messages, or unrelated people's faces.")
        for field in self.fields.values():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs.setdefault("class", "form-select")
        if self.instance.pk and self.instance.report_type == ItemReport.ReportType.FOUND:
            for index, question in enumerate(self.instance.verification_questions.all()[:3], start=1):
                self.fields[f"verification_question_{index}_type"].initial = question.question_type
                self.fields[f"verification_question_{index}_text"].initial = question.question_text
                self.fields[f"verification_question_{index}_answer"].initial = question.expected_answer

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        item_type = cleaned.get("item_type")
        legacy_post = bool(self.data.get("colour"))
        if not item_type and legacy_post:
            item_type = "not_sure"
            cleaned["item_type"] = item_type
        allowed = {value for value, label in ITEM_TYPE_CHOICES.get(category, ())}
        if item_type and item_type not in allowed:
            self.add_error("item_type", _("Select an item type that belongs to the selected category."))
        if not item_type:
            self.add_error("item_type", _("Select an item type."))
        if item_type == "other" and not cleaned.get("custom_item_type"):
            self.add_error("custom_item_type", _("Specify the item type when Other is selected."))
        if cleaned.get("brand") == "other" and not cleaned.get("custom_brand"):
            self.add_error("custom_brand", _("Specify the brand when Other is selected."))
        if self.scope == ItemReport.Scope.UNIVERSITY:
            if cleaned.get("campus_location") == "other" and not cleaned.get("custom_location"):
                self.add_error("custom_location", _("Specify a general location when Other is selected."))
            if not cleaned.get("university_location") and not cleaned.get("campus_location"):
                self.add_error("university_location", _("Choose a University location or a general campus area."))
            for name in ("country", "region", "city", "district", "place_type", "place_name", "public_location", "exact_private_location"):
                cleaned[name] = ""
        else:
            country_aliases = {"turkey": "TR", "türkiye": "TR"}
            cleaned["country"] = country_aliases.get((cleaned.get("country") or "").casefold(), cleaned.get("country"))
            if not cleaned.get("country"):
                self.add_error("country", _("Country is required for International reports."))
            if not (cleaned.get("city") or "").strip():
                self.add_error("city", _("City is required for International reports."))
            cleaned["university_location"] = None
            cleaned["campus_location"] = ""
            cleaned["custom_location"] = ""
        if item_type in {"student_id", "bank_card", "driver_licence", "national_id", "passport"} and cleaned.get("additional_images"):
            self.add_error("additional_images", _("Sensitive documents cannot have public additional images."))
        if not cleaned.get("primary_colour") and legacy_post:
            raw = " ".join(self.data.get("colour", "").split()).casefold().replace(" ", "_")
            cleaned["primary_colour"] = raw if raw in dict(COLOUR_CHOICES) else "not_sure"
        for field_name in ("additional_details", "title"):
            try:
                cleaned[field_name] = SensitiveContentModerationService.reject_public_sensitive_content(cleaned.get(field_name, ""))
            except forms.ValidationError as exc:
                self.add_error(field_name, exc)
        for index in range(1, 4):
            question_type = cleaned.get(f"verification_question_{index}_type")
            answer = cleaned.get(f"verification_question_{index}_answer", "")
            if question_type and not answer:
                self.add_error(f"verification_question_{index}_answer", _("Enter the private expected answer."))
            if answer:
                try:
                    cleaned[f"verification_question_{index}_answer"] = SensitiveContentModerationService.reject_forbidden_secret(answer)
                except forms.ValidationError as exc:
                    self.add_error(f"verification_question_{index}_answer", exc)
        return cleaned

    def clean_item_date(self):
        item_date = self.cleaned_data["item_date"]
        if item_date > timezone.localdate():
            raise forms.ValidationError(_("The date cannot be in the future."))
        return item_date

    def clean_image(self):
        return prepare_report_image(self.cleaned_data.get("image"))

    def clean_additional_images(self):
        uploads = self.cleaned_data.get("additional_images") or []
        existing_count = self.instance.additional_images.filter(is_hidden=False).count() if self.instance.pk else 0
        if existing_count + len(uploads) > 2:
            raise forms.ValidationError(_("A report may contain no more than three images total."))
        return [prepare_report_image(upload) for upload in uploads]

    def save(self, commit=True):
        report = super().save(commit=False)
        report.scope = self.scope
        report.colour = (" ".join(self.data.get("colour", "").split()) if self.data.get("colour") else (report.get_primary_colour_display() or report.primary_colour))
        report.description = self.cleaned_data.get("additional_details", "")
        if not report.title:
            report.title = self.suggested_title()
        if commit:
            report.save()
            self.save_m2m()
            next_position = 2
            used = set(report.additional_images.values_list("position", flat=True))
            for upload in self.cleaned_data.get("additional_images", []):
                while next_position in used:
                    next_position += 1
                ReportImage.objects.create(report=report, image=upload, position=next_position)
                used.add(next_position)
        return report

    def suggested_title(self):
        report_type = dict(ItemReport.ReportType.choices).get(self.report_type, self.report_type.title())
        colour = dict(COLOUR_CHOICES).get(self.cleaned_data.get("primary_colour"), "")
        brand = self.cleaned_data.get("custom_brand") if self.cleaned_data.get("brand") == "other" else dict(BRAND_CHOICES).get(self.cleaned_data.get("brand"), "")
        item_type = self.cleaned_data.get("custom_item_type") if self.cleaned_data.get("item_type") == "other" else dict(ALL_ITEM_TYPE_CHOICES).get(self.cleaned_data.get("item_type"), "")
        city = self.cleaned_data.get("city", "") if self.scope == ItemReport.Scope.INTERNATIONAL else ""
        title = " ".join(str(part) for part in (report_type, colour, brand, item_type) if part)
        return (f"{title} in {city}" if city else title)[:120]


class ReturnArrangementForm(forms.ModelForm):
    class Meta:
        model = ReturnArrangement
        fields = (
            "return_method", "status", "safe_public_location", "trusted_organization",
            "custom_arrangement", "failure_report",
        )
        widgets = {
            "custom_arrangement": forms.Textarea(attrs={"rows": 3, "dir": "auto"}),
            "failure_report": forms.Textarea(attrs={"rows": 3, "dir": "auto"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        scope = self.instance.contact_request.item_report.scope
        if scope == ItemReport.Scope.UNIVERSITY:
            methods = [choice for choice in RETURN_METHOD_CHOICES if choice[0] in {"security", "trusted_organization"}]
        else:
            methods = [choice for choice in RETURN_METHOD_CHOICES if choice[0] in {
                "safe_public_meeting", "local_authority", "private_shipping"
            }]
        self.allowed_methods = {value for value, label in methods}
        self.fields["return_method"].choices = (("", _("Choose a return method")), *methods)
        self.fields["status"].choices = RETURN_STATUS_CHOICES
        self.fields["trusted_organization"].queryset = self.fields["trusted_organization"].queryset.filter(is_verified=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("return_method") and cleaned["return_method"] not in self.allowed_methods:
            self.add_error("return_method", _("Choose a return method appropriate for this report scope."))
        for field in ("custom_arrangement", "failure_report"):
            try:
                cleaned[field] = SensitiveContentModerationService.reject_forbidden_secret(cleaned.get(field, ""))
            except forms.ValidationError as exc:
                self.add_error(field, exc)
        return cleaned


class SavedSearchForm(forms.ModelForm):
    class Meta:
        model = SavedSearch
        fields = ("name",)


class OwnershipClaimForm(forms.ModelForm):
    evidence = forms.FileField(required=False, help_text=_("Optional JPG, PNG, WebP, or PDF up to 5 MB. Mask unrelated private information."))

    class Meta:
        model = ContactRequest
        fields = ("initial_message", "loss_location", "loss_timeframe", "truthful_confirmation")
        labels = {"initial_message": _("Initial private claim message"), "loss_location": _("Where did you lose it?"),
                  "loss_timeframe": _("Approximately when did you lose it?"),
                  "truthful_confirmation": _("I confirm that this claim is truthful.")}
        widgets = {"initial_message": forms.Textarea(attrs={"rows": 4, "dir": "auto"})}

    def __init__(self, *args, item_report, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_report = item_report
        for question in item_report.verification_questions.all():
            self.fields[f"question_{question.pk}"] = forms.CharField(
                label=question.question_text or question.get_question_type_display(), max_length=1000,
                widget=forms.Textarea(attrs={"rows": 3, "dir": "auto"}),
            )

    def clean_evidence(self):
        upload = self.cleaned_data.get("evidence")
        if upload:
            validate_evidence_size(upload)
            validate_evidence_content(upload)
            FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf"))(upload)
        return upload

    def clean(self):
        cleaned = super().clean()
        for name, value in list(cleaned.items()):
            if name.startswith("question_") or name in ("initial_message", "loss_location", "loss_timeframe"):
                try:
                    cleaned[name] = SensitiveContentModerationService.reject_forbidden_secret(value)
                except forms.ValidationError as exc:
                    self.add_error(name, exc)
        if not cleaned.get("truthful_confirmation"):
            self.add_error("truthful_confirmation", _("You must confirm that the claim is truthful."))
        return cleaned


class ClarificationForm(forms.Form):
    clarification = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 4, "dir": "auto"}))

    def clean_clarification(self):
        return SensitiveContentModerationService.reject_forbidden_secret(self.cleaned_data["clarification"])


class SuspiciousClaimForm(forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 4, "dir": "auto"}))


class ClaimAppealForm(forms.ModelForm):
    class Meta:
        model = ClaimAppeal
        fields = ("reason",)
        widgets = {"reason": forms.Textarea(attrs={"rows": 5, "maxlength": 1000, "dir": "auto"})}

    def clean_reason(self):
        return SensitiveContentModerationService.reject_forbidden_secret(self.cleaned_data["reason"])


class ContentReportForm(forms.ModelForm):
    class Meta:
        model = ContentReport
        fields = ("reason",)
        widgets = {"reason": forms.Textarea(attrs={"rows": 4, "maxlength": 1000, "dir": "auto"})}

    def clean_reason(self):
        return SensitiveContentModerationService.clean(self.cleaned_data["reason"])


class ReportFilterForm(forms.Form):
    scope = forms.ChoiceField(choices=ItemReport.Scope.choices, label=_("Mode"))
    query = forms.CharField(required=False, label=_("Keyword"))
    report_type = forms.ChoiceField(
        required=False, choices=[("", _("All types")), *ItemReport.ReportType.choices]
    )
    category = forms.ChoiceField(
        required=False, choices=[("", _("All categories")), *ItemReport.Category.choices]
    )
    item_type = forms.ChoiceField(required=False, choices=(("", _("All item types")), *ALL_ITEM_TYPE_CHOICES))
    primary_colour = forms.ChoiceField(required=False, choices=(("", _("All colours")), *COLOUR_CHOICES))
    brand = forms.ChoiceField(required=False, choices=(("", _("All brands")), *BRAND_CHOICES))
    material = forms.ChoiceField(required=False, choices=(("", _("All materials")), *MATERIAL_CHOICES))
    approximate_size = forms.ChoiceField(required=False, choices=(("", _("All sizes")), *SIZE_CHOICES), label=_("Size"))
    campus_location = forms.ChoiceField(
        required=False,
        choices=[("", _("All locations")), *ItemReport.CampusLocation.choices],
    )
    university_location = forms.ModelChoiceField(
        required=False, queryset=None, label=_("Campus or building")
    )
    country = forms.ChoiceField(required=False, choices=(("", _("All countries")), *COUNTRY_CHOICES))
    region = forms.CharField(required=False, label=_("State, province, or region"))
    city = forms.CharField(required=False, label=_("City"))
    district = forms.CharField(required=False, label=_("District or area"))
    place_type = forms.ChoiceField(required=False, choices=(("", _("All place types")), *PLACE_TYPE_CHOICES))
    place_name = forms.CharField(required=False, label=_("Place name"))
    status = forms.ChoiceField(
        required=False, choices=(("", _("All public reports")), (ItemReport.Status.ACTIVE, _("Active")))
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    sort = forms.ChoiceField(
        required=False,
        choices=(("newest", _("Newest")), ("oldest", _("Oldest")), ("closest_date", _("Closest date"))),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            self.add_error("date_to", _("The end date must not be before the start date."))
        return cleaned

    def __init__(self, *args, scope=ItemReport.Scope.UNIVERSITY, include_all_scopes=False, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import UniversityLocation
        self.fields["university_location"].queryset = UniversityLocation.objects.filter(is_active=True)
        self.fields["scope"].initial = scope
        if include_all_scopes:
            self.fields["scope"].required = False
            self.fields["scope"].choices = (("", _("All modes")), *ItemReport.Scope.choices)
        elif scope == ItemReport.Scope.UNIVERSITY:
            for name in ("country", "region", "city", "district", "place_type", "place_name"):
                self.fields.pop(name)
        else:
            self.fields.pop("campus_location")
            self.fields.pop("university_location")


class AdminReportFilterForm(ReportFilterForm):
    visibility = forms.ChoiceField(
        required=False,
        choices=[("", _("All visibility")), ("visible", _("Visible")), ("hidden", _("Hidden"))],
    )

    def __init__(self, *args, **kwargs):
        kwargs["include_all_scopes"] = True
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = (("", _("All statuses")), *ItemReport.Status.choices)


class AdminUserFilterForm(forms.Form):
    query = forms.CharField(required=False, label=_("Username or email"))
    account_type = forms.ChoiceField(
        required=False,
        choices=[("", _("All account types")), ("staff", _("Staff")), ("regular", _("Regular users"))],
    )
    account_status = forms.ChoiceField(
        required=False,
        choices=[("", _("All account statuses")), ("active", _("Active")), ("inactive", _("Inactive"))],
    )


class AdminUserStatusForm(forms.Form):
    reason = forms.CharField(
        max_length=500, widget=forms.Textarea(attrs={"rows": 3, "dir": "auto"}),
        help_text=_("Required. Stored privately; audit descriptions do not copy the reason."),
    )

    def clean_reason(self):
        reason = SensitiveContentModerationService.clean(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError(_("Enter a reason for this account action."))
        return reason


class UniversityLocationForm(forms.ModelForm):
    class Meta:
        model = UniversityLocation
        fields = ("campus", "building", "general_area", "location_type", "is_active")


class CustodyRecordForm(forms.ModelForm):
    class Meta:
        model = CustodyRecord
        fields = (
            "found_report", "reference", "intake_at", "intake_point", "storage_reference",
            "status", "is_high_value", "is_locked_storage", "requires_two_staff_release", "notes",
        )
        widgets = {"intake_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
                   "notes": forms.Textarea(attrs={"rows": 3, "dir": "auto"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["found_report"].queryset = ItemReport.objects.filter(
            report_type=ItemReport.ReportType.FOUND, scope=ItemReport.Scope.UNIVERSITY,
            is_deleted=False
        ).exclude(custody_record__isnull=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_high_value") and not cleaned.get("is_locked_storage"):
            self.add_error("is_locked_storage", _("High-value items require locked storage."))
        return cleaned


class StorageIncidentForm(forms.Form):
    summary = forms.CharField(max_length=255, widget=forms.Textarea(attrs={"rows": 3, "dir": "auto"}))

    def clean_summary(self):
        return SensitiveContentModerationService.clean(self.cleaned_data["summary"])


class CustodyMovementForm(forms.Form):
    event_type = forms.ChoiceField(choices=(("move", _("Storage movement")), ("review", _("Inventory review"))))
    new_storage_reference = forms.CharField(required=False, max_length=120, label=_("New private storage reference"))
    safe_note = forms.CharField(required=False, max_length=255, widget=forms.Textarea(attrs={"rows": 2, "dir": "auto"}))

    def clean_safe_note(self):
        return SensitiveContentModerationService.clean(self.cleaned_data.get("safe_note", ""))


class CustodyReleaseForm(forms.Form):
    recipient_confirmed = forms.BooleanField(label=_("The recipient confirmed collection"))
    second_staff = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(), label=_("Second staff confirmation")
    )

    def __init__(self, *args, acting_user, custody_record, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.record = custody_record
        self.fields["second_staff"].queryset = User.objects.filter(is_staff=True, is_active=True).exclude(pk=acting_user.pk)
        self.fields["second_staff"].required = custody_record.requires_two_staff_release


class CustodyDispositionForm(forms.Form):
    disposition = forms.ChoiceField(choices=(
        ("authority_transfer", _("Transfer to an appropriate authority")),
        ("issuer_return", _("Return to card issuer")),
        ("secure_destruction", _("Secure destruction under approved policy")),
        ("donation", _("Donation under approved policy")),
        ("recycling", _("Approved recycling/data handling")),
        ("other_authorized", _("Other authorized University decision")),
    ))
    safe_note = forms.CharField(required=False, max_length=255, widget=forms.Textarea(attrs={"rows": 2, "dir": "auto"}))
