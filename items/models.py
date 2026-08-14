from pathlib import Path
import hashlib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator, MaxLengthValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .choices import (
    ALL_ITEM_TYPE_CHOICES, BRAND_CHOICES, CATEGORY_CHOICES, COLOUR_CHOICES,
    CONDITION_CHOICES, LOCATION_CHOICES, MATERIAL_CHOICES, PATTERN_CHOICES,
    PLACE_TYPE_CHOICES, RETURN_METHOD_CHOICES, RETURN_STATUS_CHOICES,
    SIZE_CHOICES, VERIFICATION_QUESTION_TYPES, ITEM_TYPE_CHOICES,
)


MAX_IMAGE_SIZE = 5 * 1024 * 1024


class PrivateMediaStorage(FileSystemStorage):
    """Private local storage whose migrations remain environment-independent."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
        super().__init__(*args, **kwargs)


private_evidence_storage = PrivateMediaStorage()


def normalize_phone_number(value):
    value = (value or "").strip()
    if not value:
        return ""
    has_country_code = value.startswith("+")
    digits = "".join(character for character in value if character.isdigit())
    return f"+{digits}" if has_country_code else digits


def validate_phone_number(value):
    raw_value = (value or "").strip()
    allowed_punctuation = set("+()- .")
    if any(not character.isdigit() and character not in allowed_punctuation for character in raw_value):
        raise ValidationError(_("Enter a valid phone number containing 7 to 15 digits."))
    if "+" in raw_value and (not raw_value.startswith("+") or raw_value.count("+") > 1):
        raise ValidationError(_("Enter a valid phone number containing 7 to 15 digits."))
    normalized = normalize_phone_number(value)
    digits = normalized.removeprefix("+")
    if normalized and (not digits.isdigit() or not 7 <= len(digits) <= 15):
        raise ValidationError(_("Enter a valid phone number containing 7 to 15 digits."))


def validate_image_size(image):
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError(_("The image must be 5 MB or smaller."))


def report_image_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"reports/user_{instance.owner_id}/{instance.report_type}_{instance.pk or 'new'}{suffix}"


def claim_evidence_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"private_claim_evidence/claim_{instance.contact_request_id}/{instance.pk or 'new'}{suffix}"


def message_attachment_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"private_message_attachments/conversation_{instance.conversation_id}/{instance.pk or 'new'}{suffix}"


def validate_evidence_size(upload):
    if upload.size > MAX_IMAGE_SIZE:
        raise ValidationError(_("Evidence files must be 5 MB or smaller."))


def validate_evidence_content(upload):
    position = upload.tell() if hasattr(upload, "tell") else 0
    header = upload.read(16)
    if hasattr(upload, "seek"):
        upload.seek(position)
    image_signatures = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")
    if not (header.startswith(b"%PDF-") or any(header.startswith(signature) for signature in image_signatures)):
        raise ValidationError(_("Upload a genuine JPG, PNG, WebP, or PDF file."))


class ItemReport(models.Model):
    class ReportType(models.TextChoices):
        LOST = "lost", _("Lost")
        FOUND = "found", _("Found")

    class Category(models.TextChoices):
        ELECTRONICS = "electronics", _("Electronics")
        BAGS = "bags", _("Bags")
        CLOTHING = "clothing", _("Clothing")
        DOCUMENTS = "documents", _("Documents")
        KEYS = "keys", _("Keys")
        WALLETS = "wallets", _("Wallets and Purses")
        JEWELLERY = "jewellery", _("Jewellery")
        BOOKS = "books", _("Books and Stationery")
        SPORTS_EQUIPMENT = "sports_equipment", _("Sports Equipment")
        PERSONAL_ACCESSORIES = "personal_accessories", _("Personal Accessories")
        OTHER = "other", _("Other")
        NOT_SURE = "not_sure", _("Not Sure")

    class CampusLocation(models.TextChoices):
        MAIN_ENTRANCE = "main_entrance", _("Main Entrance")
        LIBRARY = "library", _("Library")
        CAFETERIA = "cafeteria", _("Cafeteria")
        CLASSROOM = "classroom", _("Classroom")
        LABORATORY = "laboratory", _("Laboratory")
        STUDENT_AFFAIRS = "student_affairs", _("Student Affairs")
        SPORTS_AREA = "sports_area", _("Sports Area")
        ADMINISTRATION = "administration", _("Administration Building")
        CONFERENCE_HALL = "conference_hall", _("Conference Hall")
        UNIVERSITY_GARDEN = "university_garden", _("University Garden")
        PARKING = "parking", _("Parking Area")
        BUS_STOP = "bus_stop", _("Shuttle or Bus Stop")
        RESTROOM = "restroom", _("Restroom")
        PRAYER_AREA = "prayer_area", _("Prayer Area")
        OTHER = "other", _("Other")
        NOT_SURE = "not_sure", _("Not Sure")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        POSSIBLE_MATCH = "possible_match", _("Possible Match")
        CLAIM_IN_PROGRESS = "claim_in_progress", _("Claim in Progress")
        RETURN_ARRANGED = "return_arranged", _("Return Arranged")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")
        EXPIRED = "expired", _("Expired")
        DISPUTED = "disputed", _("Disputed")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="item_reports"
    )
    report_type = models.CharField(max_length=5, choices=ReportType.choices, db_index=True)
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1500)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    colour = models.CharField(max_length=50, db_index=True)
    item_type = models.CharField(max_length=40, choices=ALL_ITEM_TYPE_CHOICES, blank=True, db_index=True)
    custom_item_type = models.CharField(max_length=80, blank=True)
    primary_colour = models.CharField(max_length=30, choices=COLOUR_CHOICES, blank=True, db_index=True)
    secondary_colour = models.CharField(max_length=30, choices=COLOUR_CHOICES, blank=True, db_index=True)
    material = models.CharField(max_length=30, choices=MATERIAL_CHOICES, blank=True, db_index=True)
    approximate_size = models.CharField(max_length=20, choices=SIZE_CHOICES, blank=True, db_index=True)
    pattern = models.CharField(max_length=30, choices=PATTERN_CHOICES, blank=True)
    item_condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, blank=True)
    brand = models.CharField(max_length=40, choices=BRAND_CHOICES, blank=True, db_index=True)
    custom_brand = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    custom_location = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    region = models.CharField(max_length=100, blank=True, db_index=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    district = models.CharField(max_length=100, blank=True, db_index=True)
    place_type = models.CharField(max_length=32, choices=PLACE_TYPE_CHOICES, blank=True, db_index=True)
    place_name = models.CharField(max_length=160, blank=True, db_index=True)
    public_location = models.CharField(max_length=240, blank=True)
    exact_private_location = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    public_latitude = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    public_longitude = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    public_location_precision_km = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    additional_details = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    require_official_handover = models.BooleanField(default=False)
    campus_location = models.CharField(
        max_length=30, choices=CampusLocation.choices, blank=True, db_index=True
    )
    item_date = models.DateField(_("date lost or found"), db_index=True)
    image = models.ImageField(upload_to=report_image_path, validators=[validate_image_size], blank=True)
    image_sha256 = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    duplicate_confirmed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    is_hidden = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("Hidden reports are visible only to their owner and staff members."),
    )
    is_reviewed = models.BooleanField(default=False, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_item_reports",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_item_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    renewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["report_type", "status", "-created_at"]),
            models.Index(fields=["status", "country", "city", "item_date"]),
        ]

    def __str__(self):
        return f"{self.get_report_type_display()}: {self.title}"

    def get_absolute_url(self):
        return reverse("item_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.item_type and self.item_type not in {value for value, label in ITEM_TYPE_CHOICES.get(self.category, ())}:
            raise ValidationError({"item_type": _("Select an item type that belongs to the selected category.")})
        if self.item_type == "other" and not self.custom_item_type.strip():
            raise ValidationError({"custom_item_type": _("Specify the item type when Other is selected.")})
        if self.brand == "other" and not self.custom_brand.strip():
            raise ValidationError({"custom_brand": _("Specify the brand when Other is selected.")})
        if self.campus_location == "other" and not self.custom_location.strip():
            raise ValidationError({"custom_location": _("Specify a general location when Other is selected.")})
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError(_("Latitude and longitude must be supplied together."))
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": _("Latitude must be between -90 and 90.")})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": _("Longitude must be between -180 and 180.")})

    def save(self, *args, **kwargs):
        for field_name in (
            "custom_item_type", "custom_brand", "model", "custom_location", "country",
            "region", "city", "district", "place_name", "public_location", "exact_private_location",
        ):
            setattr(self, field_name, " ".join((getattr(self, field_name, "") or "").split()))
        if self.latitude is not None and self.longitude is not None:
            precision = 2 if self.public_location_precision_km >= 5 else 3
            self.public_latitude = round(self.latitude, precision)
            self.public_longitude = round(self.longitude, precision)
        else:
            self.public_latitude = self.public_longitude = None
        if self.image and not self.image_sha256:
            digest = hashlib.sha256()
            try:
                source = self.image.file
                position = source.tell()
                source.seek(0)
                for chunk in iter(lambda: source.read(64 * 1024), b""):
                    digest.update(chunk)
                source.seek(position)
            except (OSError, ValueError):
                pass
            else:
                self.image_sha256 = digest.hexdigest()
        super().save(*args, **kwargs)

    @property
    def public_details(self):
        return self.additional_details or self.description

    @property
    def public_location_display(self):
        parts = [self.place_name, self.district, self.city, self.region, self.country]
        value = ", ".join(part for part in parts if part)
        return value or self.public_location or self.custom_location or self.get_campus_location_display()

    def can_view_private_location(self, user):
        if not user.is_authenticated:
            return False
        if user.is_staff or user.pk == self.owner_id:
            return True
        return self.contact_requests.filter(
            status__in=(ContactRequest.Status.APPROVED, ContactRequest.Status.RETURN_IN_PROGRESS),
            requesting_user=user,
        ).exists()


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone_number = models.CharField(
        max_length=16, blank=True, validators=[validate_phone_number]
    )
    consent_to_share_phone = models.BooleanField(
        default=False,
        help_text=_(
            "When enabled, your phone number is shown only after staff approve a contact request. You can revoke consent at any time."
        ),
    )
    mask_phone_number = models.BooleanField(
        default=True,
        help_text=_("Show active conversation contacts only the final four digits of your phone number."),
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=80, blank=True)
    preferred_language = models.CharField(
        max_length=8, choices=(("en", "English"), ("tr", "Türkçe"), ("ar", "العربية")), default="en"
    )
    notify_strong_matches = models.BooleanField(default=True)
    notify_claim_updates = models.BooleanField(default=True)
    notify_messages = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)
    is_deactivation_requested = models.BooleanField(default=False)
    deactivation_requested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = (
            ("view_unmasked_phone_numbers", "Can view unmasked shared phone numbers"),
        )

    def clean(self):
        super().clean()
        validate_phone_number(self.phone_number)
        self.phone_number = normalize_phone_number(self.phone_number)

    def save(self, *args, **kwargs):
        self.phone_number = normalize_phone_number(self.phone_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile for {self.user.username}"


class UserBlock(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_user_relationships",
    )
    blocked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_by_relationships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked_user"), name="unique_user_block"
            ),
            models.CheckConstraint(
                condition=~Q(blocker=models.F("blocked_user")),
                name="user_cannot_block_self",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked_user}"


class ContactRequest(models.Model):
    class RequestType(models.TextChoices):
        OWNERSHIP_CLAIM = "ownership_claim", _("Ownership Claim")
        FOUND_ITEM = "found_item", _("Found Item")

    class Status(models.TextChoices):
        INITIATED = "initiated", _("Conversation Started")
        PENDING = "pending", _("Pending")
        MORE_INFORMATION = "more_information", _("More Information Requested")
        APPROVED = "approved", _("Approved")
        DENIED = "denied", _("Denied")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")
        RETURN_IN_PROGRESS = "return_in_progress", _("Return in Progress")
        COMPLETED = "completed", _("Completed")
        DISPUTED = "disputed", _("Disputed")
        REVOKED = "revoked", _("Revoked")

    item_report = models.ForeignKey(
        ItemReport, on_delete=models.CASCADE, related_name="contact_requests"
    )
    requesting_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_contact_requests",
    )
    receiving_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_contact_requests",
    )
    request_type = models.CharField(max_length=24, choices=RequestType.choices)
    initial_message = models.TextField(validators=[MaxLengthValidator(2000)])
    private_details = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    loss_location = models.CharField(max_length=200, blank=True)
    loss_timeframe = models.CharField(max_length=200, blank=True)
    truthful_confirmation = models.BooleanField(default=False)
    clarification_request = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    clarification_answer = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    attempt_number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_contact_requests",
    )
    admin_note = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(requesting_user=models.F("receiving_user")),
                name="contact_request_different_users",
            ),
            models.UniqueConstraint(
                fields=("item_report", "requesting_user", "receiving_user"),
                condition=Q(status__in=("pending", "more_information")),
                name="unique_pending_contact_request",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.requesting_user_id is not None
            and self.requesting_user_id == self.receiving_user_id
        ):
            raise ValidationError(_("You cannot send a contact request to yourself."))
        if (
            self.item_report_id
            and self.receiving_user_id is not None
            and self.receiving_user_id != self.item_report.owner_id
        ):
            raise ValidationError(_("The request recipient must own the item report."))
        if self.item_report_id:
            expected_type = (
                self.RequestType.OWNERSHIP_CLAIM
                if self.item_report.report_type == ItemReport.ReportType.FOUND
                else self.RequestType.FOUND_ITEM
            )
            if self.request_type and self.request_type != expected_type:
                raise ValidationError(_("The request type does not match this report."))

    def can_view(self, user):
        return user.is_authenticated and (
            user.is_staff or user.pk in (self.requesting_user_id, self.receiving_user_id)
        )

    def __str__(self):
        return f"{self.get_request_type_display()} for {self.item_report.title}"


class PrivateVerificationQuestion(models.Model):
    item_report = models.ForeignKey(ItemReport, on_delete=models.CASCADE, related_name="verification_questions")
    question_type = models.CharField(max_length=30, choices=VERIFICATION_QUESTION_TYPES)
    question_text = models.CharField(max_length=240, blank=True)
    expected_answer = models.TextField(max_length=500)
    position = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ("position", "pk")
        constraints = [models.UniqueConstraint(fields=("item_report", "position"), name="unique_verification_position")]

    def can_view_expected_answer(self, user):
        return user.is_authenticated and (user.is_staff or user.pk == self.item_report.owner_id)

    def __str__(self):
        return self.question_text or self.get_question_type_display()


class ClaimAnswer(models.Model):
    contact_request = models.ForeignKey(ContactRequest, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(PrivateVerificationQuestion, on_delete=models.CASCADE, related_name="claim_answers")
    answer = models.TextField(max_length=1000)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("contact_request", "question"), name="unique_claim_question_answer")]


class ClaimEvidence(models.Model):
    contact_request = models.ForeignKey(ContactRequest, on_delete=models.CASCADE, related_name="evidence_files")
    file = models.FileField(storage=private_evidence_storage, upload_to=claim_evidence_path, validators=[validate_evidence_size, validate_evidence_content, FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf"))])
    uploaded_at = models.DateTimeField(auto_now_add=True)


class HandoverConfirmation(models.Model):
    contact_request = models.ForeignKey(ContactRequest, on_delete=models.CASCADE, related_name="handover_confirmations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="handover_confirmations")
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("contact_request", "user"), name="unique_handover_confirmation")]


class SuspiciousClaimReport(models.Model):
    contact_request = models.OneToOneField(ContactRequest, on_delete=models.CASCADE, related_name="suspicion_report")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reported_suspicious_claims")
    reason = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)


class TrustedOrganization(models.Model):
    class OrganizationType(models.TextChoices):
        UNIVERSITY = "university", _("University or school")
        POLICE_SECURITY = "police_security", _("Police or security office")
        AIRPORT = "airport", _("Airport")
        SHOPPING_CENTRE = "shopping_centre", _("Shopping centre")
        HOTEL = "hotel", _("Hotel")
        PUBLIC_TRANSPORT = "public_transport", _("Public transport lost-property office")
        COMPANY_SECURITY = "company_security", _("Company security department")
        OTHER = "other", _("Other official lost-property organization")

    name = models.CharField(max_length=160)
    organization_type = models.CharField(max_length=32, choices=OrganizationType.choices, db_index=True)
    country = models.CharField(max_length=100, db_index=True)
    city = models.CharField(max_length=100, db_index=True)
    public_location = models.CharField(max_length=240)
    public_contact = models.CharField(max_length=200, blank=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="verified_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("name", "country", "city"), name="unique_trusted_organization_location")
        ]

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        STAFF = "staff", _("Organization staff")
        MANAGER = "manager", _("Organization manager")

    organization = models.ForeignKey(TrustedOrganization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_organization_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("organization", "user"), name="unique_organization_member")]


class ReturnArrangement(models.Model):
    contact_request = models.OneToOneField(ContactRequest, on_delete=models.CASCADE, related_name="return_arrangement")
    return_method = models.CharField(max_length=32, choices=RETURN_METHOD_CHOICES, blank=True)
    status = models.CharField(max_length=24, choices=RETURN_STATUS_CHOICES, default="arranging", db_index=True)
    safe_public_location = models.CharField(max_length=240, blank=True)
    trusted_organization = models.ForeignKey(
        TrustedOrganization, null=True, blank=True, on_delete=models.SET_NULL, related_name="return_arrangements"
    )
    custom_arrangement = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    delivery_address = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    address_shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="shared_delivery_addresses",
    )
    address_consent_at = models.DateTimeField(null=True, blank=True)
    address_consent_withdrawn_at = models.DateTimeField(null=True, blank=True)
    delivery_cost_payer = models.CharField(
        max_length=16, blank=True,
        choices=(("finder", _("Finder")), ("owner", _("Owner")), ("shared", _("Shared")), ("none", _("No delivery cost"))),
    )
    courier_name = models.CharField(max_length=100, blank=True)
    tracking_reference = models.CharField(max_length=160, blank=True)
    handover_reference = models.CharField(max_length=80, blank=True)
    failure_report = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])
    finder_confirmed_at = models.DateTimeField(null=True, blank=True)
    owner_confirmed_at = models.DateTimeField(null=True, blank=True)
    delivery_details_retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    legal_or_safety_hold = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = (("manage_return_disputes", "Can manage return disputes"),)

    def clean(self):
        super().clean()
        if self.return_method == "courier_post" and self.delivery_address and not self.address_consent_at:
            raise ValidationError({"delivery_address": _("Address sharing requires the owner's explicit consent.")})
        if self.trusted_organization_id and not self.trusted_organization.is_verified:
            raise ValidationError({"trusted_organization": _("Choose an administrator-approved organization.")})

    def can_view(self, user):
        claim = self.contact_request
        return user.is_authenticated and (
            user.is_staff or user.pk in (claim.requesting_user_id, claim.receiving_user_id)
        )

    def can_view_delivery_address(self, user):
        if not self.can_view(user) or self.address_consent_withdrawn_at:
            return False
        return bool(user.is_staff or (self.address_consent_at and user.pk in (
            self.contact_request.requesting_user_id, self.contact_request.receiving_user_id
        )))


class CustodyEvent(models.Model):
    arrangement = models.ForeignKey(ReturnArrangement, on_delete=models.CASCADE, related_name="custody_events")
    organization = models.ForeignKey(TrustedOrganization, null=True, blank=True, on_delete=models.SET_NULL)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    event_type = models.CharField(
        max_length=24,
        choices=(("accepted", _("Accepted into custody")), ("released", _("Released for collection")), ("collected", _("Collected"))),
    )
    handover_reference = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)


class Conversation(models.Model):
    class DealStatus(models.TextChoices):
        ACTIVE = "active", _("Active")
        DEACTIVATED = "deactivated", _("Deactivated")
        COMPLETED = "completed", _("Completed")
        CLOSED = "closed", _("Closed")

    item_report = models.ForeignKey(
        ItemReport, on_delete=models.CASCADE, related_name="conversations"
    )
    approved_contact_request = models.OneToOneField(
        ContactRequest, on_delete=models.CASCADE, related_name="conversation"
    )
    first_participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_first",
    )
    second_participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_second",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=12, choices=DealStatus.choices, default=DealStatus.ACTIVE, db_index=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_conversations",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_conversations",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reopened_conversations",
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deactivated_conversations",
    )
    deactivation_reason = models.TextField(
        blank=True, validators=[MaxLengthValidator(1000)]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("item_report", "first_participant", "second_participant"),
                name="unique_report_participant_conversation",
            ),
        ]

    def can_view(self, user):
        return user.is_authenticated and (
            user.is_staff or user.pk in (self.first_participant_id, self.second_participant_id)
        )

    def other_participant(self, user):
        if user.pk == self.first_participant_id:
            return self.second_participant
        if user.pk == self.second_participant_id:
            return self.first_participant
        return None

    def __str__(self):
        return f"Conversation for {self.item_report.title}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contact_messages"
    )
    body = models.TextField(validators=[MaxLengthValidator(2000)])
    attachment = models.FileField(
        storage=private_evidence_storage, upload_to=message_attachment_path, blank=True,
        validators=[validate_evidence_size, validate_evidence_content, FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf"))],
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["sent_at"]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError({"body": _("A message cannot be empty.")})
        if self.conversation_id and self.sender_id not in (
            self.conversation.first_participant_id,
            self.conversation.second_participant_id,
        ):
            raise ValidationError(_("The sender must be a conversation participant."))

    def __str__(self):
        return f"Message {self.pk or 'new'} in conversation {self.conversation_id}"


class ContactAuditLog(models.Model):
    class EventType(models.TextChoices):
        REQUEST_CREATED = "request_created", _("Contact request created")
        REQUEST_CANCELLED = "request_cancelled", _("Contact request cancelled")
        REQUEST_APPROVED = "request_approved", _("Request approved")
        REQUEST_DENIED = "request_denied", _("Request denied")
        REQUEST_MORE_INFORMATION = "request_more_info", _("More information requested")
        ADDITIONAL_ANSWER = "additional_answer", _("Additional answer submitted")
        CLAIM_DISPUTED = "claim_disputed", _("Claim disputed")
        SUSPICIOUS_CLAIM = "suspicious_claim", _("Suspicious claim reported")
        PERMISSION_REVOKED = "permission_revoked", _("Permission revoked")
        CONVERSATION_OPENED = "conversation_opened", _("Conversation opened")
        MESSAGE_SENT = "message_sent", _("Message sent")
        MESSAGE_READ = "message_read", _("Message read")
        PHONE_GRANTED = "phone_granted", _("Phone-number access granted")
        PHONE_BLOCKED = "phone_blocked", _("Phone-number access blocked")
        PHONE_MASKED = "phone_masked", _("Masked phone number displayed")
        BULK_REPORT_ACTION = "bulk_report_action", _("Bulk report action")
        DEAL_COMPLETED = "deal_completed", _("Deal completed")
        RETURN_UPDATED = "return_updated", _("Return updated")
        CONVERSATION_REOPENED = "conversation_reopened", _("Conversation reopened")
        CONVERSATION_DEACTIVATED = "conversation_deactivated", _("Conversation deactivated")
        USER_SUSPENDED = "user_suspended", _("User suspended")
        USER_RESTORED = "user_restored", _("User restored")

    acting_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="contact_audit_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    item_report = models.ForeignKey(
        ItemReport, on_delete=models.SET_NULL, null=True, related_name="contact_audit_events"
    )
    contact_request = models.ForeignKey(
        ContactRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return self.get_event_type_display()


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        STRONG_MATCH = "strong_match", _("Strong Possible Match")
        NEW_CLAIM = "new_claim", _("New Claim")
        CLAIM_UPDATED = "claim_updated", _("Claim Updated")
        NEW_MESSAGE = "new_message", _("New Message")
        RETURN_UPDATED = "return_updated", _("Return Updated")
        SAVED_SEARCH_MATCH = "saved_search_match", _("Saved Search Match")
        EXPIRATION_WARNING = "expiration_warning", _("Report Expiration Warning")
        DEAL_COMPLETED = "deal_completed", _("Deal Completed")
        CONVERSATION_REOPENED = "conversation_reopened", _("Conversation Reopened")
        CONVERSATION_DEACTIVATED = "conversation_deactivated", _("Conversation Deactivated")
        CONTACT_APPROVED = "contact_approved", _("Contact Request Approved")
        CONTACT_DENIED = "contact_denied", _("Contact Request Denied")
        REPORT_STATUS_CHANGED = "report_status_changed", _("Report Status Changed")
        ADMIN_NOTICE = "admin_notice", _("Administrator Notice")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(
        max_length=28, choices=NotificationType.choices, db_index=True
    )
    title = models.CharField(max_length=100)
    safe_message = models.CharField(max_length=255)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    item_report = models.ForeignKey(
        ItemReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    destination_url = models.CharField(max_length=255, blank=True)
    deduplication_key = models.CharField(max_length=160, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_notification_type_display()} for {self.recipient.username}"


class SavedSearch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [models.UniqueConstraint(fields=("user", "name"), name="unique_saved_search_name_per_user")]

    @staticmethod
    def public_filter_keys():
        return {
            "report_type", "country", "region", "city", "district", "place_type", "place_name",
            "category", "item_type", "primary_colour", "brand", "material", "approximate_size",
            "date_from", "date_to",
        }

    def clean(self):
        super().clean()
        unknown = set(self.filters) - self.public_filter_keys()
        if unknown:
            raise ValidationError({"filters": _("Saved searches may contain only public report filters.")})


class SavedSearchNotification(models.Model):
    saved_search = models.ForeignKey(SavedSearch, on_delete=models.CASCADE, related_name="matched_reports")
    item_report = models.ForeignKey(ItemReport, on_delete=models.CASCADE, related_name="saved_search_notifications")
    notification = models.OneToOneField(Notification, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("saved_search", "item_report"), name="unique_saved_search_report_alert")
        ]


class ContentReport(models.Model):
    class TargetType(models.TextChoices):
        ITEM_REPORT = "item_report", _("Item report")
        MESSAGE = "message", _("Message")
        USER = "user", _("User")
        RETURN = "return", _("Return or delivery")

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submitted_content_reports")
    target_type = models.CharField(max_length=16, choices=TargetType.choices, db_index=True)
    target_identifier = models.PositiveBigIntegerField()
    reason = models.TextField(max_length=1000)
    status = models.CharField(
        max_length=16, choices=(("open", _("Open")), ("reviewed", _("Reviewed")), ("closed", _("Closed"))),
        default="open", db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("reporter", "target_type", "target_identifier"),
                condition=Q(status="open"), name="unique_open_content_report",
            )
        ]
