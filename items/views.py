from pathlib import Path
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, connection, models, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext as _

from .communications import phone_number_access, record_contact_event
from .forms import (
    AdminReportFilterForm,
    AdminUserFilterForm,
    AdminUserStatusForm,
    ContactRequestForm,
    ClarificationForm,
    ClaimAppealForm,
    ContentReportForm,
    ConversationDeactivateForm,
    ConversationReopenForm,
    CustodyRecordForm,
    CustodyDispositionForm,
    CustodyMovementForm,
    CustodyReleaseForm,
    ItemReportForm,
    OwnershipClaimForm,
    SuspiciousClaimForm,
    MessageForm,
    RegistrationForm,
    ReportFilterForm,
    ReturnArrangementForm,
    SavedSearchForm,
    StorageIncidentForm,
    UserProfileForm,
    UniversityLocationForm,
)
from .admin_actions import AdminReportActionService
from .deals import DealService
from .moderation import SensitiveContentModerationService
from .models import (
    ContactAuditLog,
    ContactRequest,
    ClaimAnswer,
    ClaimAppeal,
    ClaimEvidence,
    Conversation,
    ContentReport,
    CustodyMovement,
    CustodyRecord,
    DismissedMatch,
    ItemReport,
    Message,
    Notification,
    PrivateVerificationQuestion,
    ReturnArrangement,
    SavedSearch,
    SuspiciousClaimReport,
    StorageIncident,
    UserBlock,
    UserProfile,
    UniversityLocation,
)
from .notification_service import NotificationService
from .conversation_service import ConversationInitiationService
from .services import MatchingService
from .ownership import OwnershipVerificationService
from .alerts import AlertService
from .duplicates import DuplicateReportService
from .return_service import ReturnWorkflowService
from .security import (
    EmailVerificationService, RateLimitService, has_recent_authentication,
    mark_recent_authentication,
)
from .lifecycle import ReportLifecycleService
from .university import UniversityAccessService, verified_scope_required as verified_university_required


class RoleAwareLoginView(LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        requested_url = self.get_redirect_url()
        if requested_url:
            return requested_url
        if self.request.user.is_staff:
            return reverse("management_dashboard")
        return reverse("home")

    def form_invalid(self, form):
        try:
            RateLimitService.check(self.request, "login")
        except ValidationError as exc:
            form.add_error(None, exc)
        return super().form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        mark_recent_authentication(self.request)
        return response


def _require_report_scope(user, report):
    UniversityAccessService.require_scope(user, report.scope)


def _recent_auth_redirect(request):
    if has_recent_authentication(request):
        return None
    return redirect(f"{reverse('reauthenticate')}?next={request.get_full_path()}")


def home(request):
    active_scope = UniversityAccessService.active_scope(request)
    recent_reports = ItemReport.objects.filter(
        scope=active_scope, status=ItemReport.Status.ACTIVE, is_hidden=False, is_deleted=False
    ).select_related("owner")[:6]
    public_reports = ItemReport.objects.filter(scope=active_scope, is_hidden=False, is_deleted=False)
    preview_matches = []
    preview_lost_reports = public_reports.filter(
        report_type=ItemReport.ReportType.LOST,
        status__in=[ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH],
    )[:8]
    for lost_report in preview_lost_reports:
        preview_matches.extend(MatchingService.find_matches(lost_report, public_reports))
    hero_match = max(preview_matches, key=lambda match: match.total_score, default=None)
    context = {
        "recent_reports": recent_reports,
        "lost_reports": public_reports.filter(report_type=ItemReport.ReportType.LOST).count(),
        "found_reports": public_reports.filter(report_type=ItemReport.ReportType.FOUND).count(),
        "possible_matches": len(
            {(match.lost_item.pk, match.found_item.pk) for match in preview_matches}
        ),
        "resolved_reports": public_reports.filter(status=ItemReport.Status.RESOLVED).count(),
        "hero_match": hero_match,
        "active_scope": active_scope,
    }
    return render(request, "items/home.html", context)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        EmailVerificationService.send(request, user)
        login(request, user)
        mark_recent_authentication(request)
        messages.success(request, _("Welcome to FindMatch. Open the signed verification link printed in the server terminal to unlock your account."))
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


def switch_scope(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    scope = request.POST.get("scope", "")
    if scope not in ItemReport.Scope.values:
        raise Http404
    if request.user.is_authenticated and UniversityAccessService.has_verified_email(request.user):
        UniversityAccessService.require_scope(request.user, scope)
    request.session["findmatch_scope"] = scope
    if request.user.is_authenticated:
        profile = UniversityAccessService.profile_for(request.user)
        profile.preferred_scope = scope
        profile.save(update_fields=("preferred_scope", "updated_at"))
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("item_list")
    return redirect(next_url)


@login_required
def reauthenticate(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.get_user().pk != request.user.pk:
            form.add_error(None, _("Re-enter the password for the currently signed-in account."))
        else:
            mark_recent_authentication(request)
            next_url = request.POST.get("next", "")
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = reverse("profile")
            messages.success(request, _("Your identity was confirmed."))
            return redirect(next_url)
    return render(request, "registration/reauthenticate.html", {
        "form": form, "next": request.GET.get("next") or request.POST.get("next", "")
    })


def report_list(request, report_type=None):
    active_scope = UniversityAccessService.active_scope(request)
    reports = ItemReport.objects.filter(
        scope=active_scope, status=ItemReport.Status.ACTIVE, is_hidden=False, is_deleted=False
    ).select_related("owner")
    filter_data = request.GET.copy()
    if report_type in ItemReport.ReportType.values:
        filter_data["report_type"] = report_type
    filter_data["scope"] = active_scope
    form = ReportFilterForm(filter_data, scope=active_scope)
    active_filters = []
    if form.is_valid():
        data = form.cleaned_data
        if data["query"]:
            reports = reports.filter(
                Q(title__icontains=data["query"])
                | Q(description__icontains=data["query"])
            )
        for field in (
            "report_type", "category", "item_type", "primary_colour", "brand", "material",
            "approximate_size", "campus_location", "university_location", "country", "region",
            "city", "district", "place_type", "place_name",
        ):
            if data.get(field):
                lookup = field if field in {
                    "report_type", "category", "item_type", "primary_colour", "brand", "material",
                    "approximate_size", "campus_location", "university_location", "place_type",
                } else f"{field}__iexact"
                reports = reports.filter(**{lookup: data[field]})
        if data["date_from"]:
            reports = reports.filter(item_date__gte=data["date_from"])
        if data["date_to"]:
            reports = reports.filter(item_date__lte=data["date_to"])
        if data.get("status"):
            reports = reports.filter(status=data["status"])
        ordering = {"oldest": "created_at", "closest_date": "-item_date", "newest": "-created_at"}
        reports = reports.order_by(ordering.get(data.get("sort"), "-created_at"))
        for name, value in data.items():
            if name in {"query", "sort", "status", "report_type", "scope"} or not value:
                continue
            field = form.fields[name]
            display_value = value
            if getattr(field, "choices", None):
                display_value = dict(field.choices).get(value, value)
            without_filter = request.GET.copy()
            without_filter.pop(name, None)
            active_filters.append({
                "label": field.label,
                "value": display_value,
                "remove_url": f"{request.path}?{without_filter.urlencode()}" if without_filter else request.path,
            })
    paginator = Paginator(reports, 9)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "items/report_list.html",
        {
            "form": form,
            "page_obj": page_obj,
            "query_string": query_params.urlencode(),
            "active_filters": active_filters,
            "active_filter_count": len(active_filters),
            "locked_report_type": report_type,
            "active_scope": active_scope,
            "list_title": (
                f"Browse {report_type} items" if report_type else "Browse lost and found items"
            ),
            "clear_url": reverse(f"{report_type}_item_list" if report_type else "item_list") + f"?scope={active_scope}",
        },
    )


def report_detail(request, pk):
    report = get_object_or_404(ItemReport.objects.select_related("owner"), pk=pk)
    if report.is_deleted and not request.user.is_staff:
        raise Http404
    if report.is_hidden and not request.user.is_staff and request.user != report.owner:
        raise Http404
    return render(request, "items/report_detail.html", {"report": report})


def can_manage(user, report):
    return user.is_authenticated and (user == report.owner or user.is_staff)


def _save_verification_questions(report, form):
    if report.report_type != ItemReport.ReportType.FOUND:
        return
    report.verification_questions.all().delete()
    for index in range(1, 4):
        question_type = form.cleaned_data.get(f"verification_question_{index}_type")
        if question_type:
            PrivateVerificationQuestion.objects.create(
                item_report=report, question_type=question_type,
                question_text=form.cleaned_data.get(f"verification_question_{index}_text", ""),
                expected_answer=form.cleaned_data[f"verification_question_{index}_answer"], position=index,
            )


@verified_university_required
def report_create(request, report_type):
    if report_type not in ItemReport.ReportType.values:
        raise PermissionDenied(_("Unknown report type."))
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    form = ItemReportForm(
        request.POST or None, request.FILES or None, report_type=report_type, scope=active_scope
    )
    if request.method == "POST":
        try:
            RateLimitService.check(request, "report")
        except ValidationError as exc:
            form.add_error(None, exc)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.owner = request.user
        report.report_type = report_type
        report.scope = active_scope
        report.status = ItemReport.Status.DRAFT if request.POST.get("submission_action") == "draft" else ItemReport.Status.ACTIVE
        duplicates = DuplicateReportService.candidates(report)
        if duplicates and not form.cleaned_data.get("duplicate_confirmed"):
            form.add_error(None, _("This looks similar to one of your recent reports. Review it, then confirm if this is a separate item."))
            form.data = form.data.copy()
            form.data["duplicate_confirmed"] = "1"
            return render(request, "items/report_form.html", {"form": form, "report_type": report_type, "editing": False, "possible_duplicates": duplicates, "active_scope": active_scope})
        report.save()
        for position, upload in enumerate(form.cleaned_data.get("additional_images", []), start=2):
            report.additional_images.create(image=upload, position=position)
        ReportLifecycleService.initialize_expiration(report)
        _save_verification_questions(report, form)
        if report.status == ItemReport.Status.ACTIVE:
            AlertService.notify_saved_searches(report)
            AlertService.notify_strong_matches(report)
            messages.success(request, _("Your report was submitted successfully."))
            return redirect("item_matches", pk=report.pk)
        messages.success(request, _("Your private draft was saved."))
        return redirect("my_reports")
    return render(
        request,
        "items/report_form.html",
        {"form": form, "report_type": report_type, "editing": False, "active_scope": active_scope},
    )


@verified_university_required
def report_edit(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    _require_report_scope(request.user, report)
    if not can_manage(request.user, report):
        raise PermissionDenied
    if (
        report.status in [ItemReport.Status.RESOLVED, ItemReport.Status.CLOSED]
        and not request.user.is_staff
    ):
        messages.error(request, _("Resolved or closed reports cannot be edited."))
        return redirect(report)
    form = ItemReportForm(
        request.POST or None, request.FILES or None, instance=report,
        report_type=report.report_type, scope=report.scope,
    )
    if request.method == "POST" and form.is_valid():
        saved_report = form.save()
        _save_verification_questions(saved_report, form)
        if saved_report.status == ItemReport.Status.ACTIVE:
            AlertService.notify_saved_searches(saved_report)
            AlertService.notify_strong_matches(saved_report)
        messages.success(request, _("Your report was updated."))
        return redirect(report)
    return render(
        request,
        "items/report_form.html",
        {"form": form, "report_type": report.report_type, "editing": True, "active_scope": report.scope},
    )


@verified_university_required
def my_reports(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    all_reports = request.user.item_reports.filter(scope=active_scope, is_deleted=False)
    reports = all_reports
    report_type = request.GET.get("report_type", "")
    status = request.GET.get("status", "")
    if report_type in ItemReport.ReportType.values:
        reports = reports.filter(report_type=report_type)
    if status in ItemReport.Status.values:
        reports = reports.filter(status=status)
    context = {
        "reports": reports,
        "total_count": all_reports.count(),
        "active_count": all_reports.filter(
            status__in=[ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH]
        ).count(),
        "resolved_count": all_reports.filter(status=ItemReport.Status.RESOLVED).count(),
        "lost_count": all_reports.filter(report_type=ItemReport.ReportType.LOST).count(),
        "found_count": all_reports.filter(report_type=ItemReport.ReportType.FOUND).count(),
        "selected_type": report_type,
        "selected_status": status,
        "active_scope": active_scope,
    }
    return render(request, "items/my_reports.html", context)


@verified_university_required
def user_dashboard(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    reports = request.user.item_reports.filter(scope=active_scope, is_deleted=False)
    claims_sent = request.user.sent_contact_requests.filter(item_report__scope=active_scope).select_related("item_report")
    claims_received = request.user.received_contact_requests.filter(item_report__scope=active_scope).select_related("item_report")
    conversations = Conversation.objects.filter(
        Q(first_participant=request.user) | Q(second_participant=request.user)
    ).filter(item_report__scope=active_scope).select_related("item_report", "approved_contact_request")
    urgent_claims = claims_received.filter(status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION))[:5]
    return render(request, "accounts/dashboard.html", {
        "urgent_claims": urgent_claims,
        "active_lost": reports.filter(report_type="lost", status=ItemReport.Status.ACTIVE)[:5],
        "active_found": reports.filter(report_type="found", status=ItemReport.Status.ACTIVE)[:5],
        "claims_sent": claims_sent[:5], "claims_received": claims_received[:5],
        "conversations": conversations[:5],
        "return_arrangements": ReturnArrangement.objects.filter(
            Q(contact_request__requesting_user=request.user) | Q(contact_request__receiving_user=request.user)
        ).select_related("contact_request__item_report")[:5],
        "saved_searches": request.user.saved_searches.all()[:5],
        "unread_notifications": request.user.notifications.filter(is_read=False)[:5],
        "resolved_count": reports.filter(status=ItemReport.Status.RESOLVED).count(),
        "active_count": reports.filter(status=ItemReport.Status.ACTIVE).count(),
        "active_scope": active_scope,
    })


@verified_university_required
def possible_matches(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    if not can_manage(request.user, report):
        raise PermissionDenied
    _require_report_scope(request.user, report)
    matches = MatchingService.find_matches(report)
    try:
        minimum_score = max(70, min(100, int(request.GET.get("minimum_score", 70))))
    except ValueError:
        minimum_score = 70
    dismissed = set(DismissedMatch.objects.filter(user=request.user).values_list("lost_report_id", "found_report_id"))
    matches = [
        match for match in matches
        if match.total_score >= minimum_score
        and (match.lost_item.pk, match.found_item.pk) not in dismissed
    ]
    return render(
        request, "items/possible_matches.html", {"report": report, "matches": matches, "minimum_score": minimum_score}
    )


@verified_university_required
def my_possible_matches(request):
    report_groups = []
    dismissed = set(DismissedMatch.objects.filter(user=request.user).values_list("lost_report_id", "found_report_id"))
    try:
        minimum_score = max(70, min(100, int(request.GET.get("minimum_score", 70))))
    except ValueError:
        minimum_score = 70
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    reports = request.user.item_reports.filter(
        scope=active_scope,
        status__in=[ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH],
        is_deleted=False,
    )
    for report in reports:
        matches = [
            match for match in MatchingService.find_matches(report)
            if match.total_score >= minimum_score
            and (match.lost_item.pk, match.found_item.pk) not in dismissed
        ]
        if matches:
            report_groups.append({"report": report, "matches": matches})
    return render(
        request,
        "items/my_possible_matches.html",
        {"report_groups": report_groups, "minimum_score": minimum_score, "active_scope": active_scope},
    )


@login_required
def profile_detail(request):
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/profile.html", {"profile": profile})


@login_required
def profile_edit(request):
    if request.method == "POST":
        recent_redirect = _recent_auth_redirect(request)
        if recent_redirect:
            return recent_redirect
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    form = UserProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        profile = form.save()
        request.session["findmatch_scope"] = profile.preferred_scope
        messages.success(request, _("Your contact preferences were updated."))
        return redirect("profile")
    return render(request, "accounts/profile_form.html", {"form": form})


@verified_university_required
def contact_request_create(request, pk):
    item_report = get_object_or_404(ItemReport, pk=pk, is_hidden=False, is_deleted=False)
    _require_report_scope(request.user, item_report)
    is_ownership_claim = item_report.report_type == ItemReport.ReportType.FOUND
    form = (OwnershipClaimForm(request.POST or None, request.FILES or None, item_report=item_report)
            if is_ownership_claim else ContactRequestForm(request.POST or None))
    if request.user == item_report.owner:
        raise PermissionDenied(_("You cannot contact yourself about your own report."))
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    if is_ownership_claim and not profile.email_verified_at:
        raise PermissionDenied(_("Verify your email address before submitting an ownership claim."))
    if item_report.status == ItemReport.Status.CLOSED:
        raise PermissionDenied(_("This report is closed and is not available for contact."))
    if UserBlock.objects.filter(
        blocker=item_report.owner, blocked_user=request.user
    ).exists():
        raise PermissionDenied(_("You cannot contact this report owner."))
    existing_conversation = ConversationInitiationService.existing_conversation(item_report=item_report, first_user=request.user, second_user=item_report.owner)
    if existing_conversation:
        messages.info(request, _("You already have a conversation about this report."))
        return redirect("conversation_detail", pk=existing_conversation.pk)
    if request.method == "POST":
        try:
            RateLimitService.check(request, "claim")
        except ValidationError as exc:
            form.add_error(None, exc)
    if request.method == "POST" and form.is_valid():
        try:
            if is_ownership_claim:
                claim = OwnershipVerificationService.submit(report=item_report, claimant=request.user, form=form)
                messages.success(request, _("Your private ownership claim was submitted for review."))
                return redirect("contact_request_detail", pk=claim.pk)
            conversation, created = ConversationInitiationService.start(item_report=item_report, initiating_user=request.user, initial_message=form.cleaned_data["initial_message"])
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("Your private conversation was started.")
                if created
                else _("Your existing conversation was opened."),
            )
            return redirect("conversation_detail", pk=conversation.pk)
    return render(
        request,
        "contacts/request_form.html",
        {
            "form": form,
            "item_report": item_report,
            "is_ownership_claim": is_ownership_claim,
        },
    )


@verified_university_required
def contact_requests_sent(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    contact_requests = request.user.sent_contact_requests.filter(item_report__scope=active_scope).select_related(
        "item_report", "receiving_user"
    )
    return render(
        request, "contacts/request_list.html", {"contact_requests": contact_requests, "sent": True}
    )


@verified_university_required
def contact_requests_received(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    contact_requests = request.user.received_contact_requests.filter(item_report__scope=active_scope).select_related(
        "item_report", "requesting_user"
    )
    return render(
        request,
        "contacts/request_list.html",
        {"contact_requests": contact_requests, "sent": False},
    )


@verified_university_required
def contact_request_detail(request, pk):
    contact_request = get_object_or_404(
        ContactRequest.objects.select_related(
            "item_report", "requesting_user", "receiving_user", "reviewed_by"
        ),
        pk=pk,
    )
    if not contact_request.can_view(request.user):
        raise PermissionDenied
    _require_report_scope(request.user, contact_request.item_report)
    conversation = getattr(contact_request, "conversation", None)
    is_claim = contact_request.request_type == ContactRequest.RequestType.OWNERSHIP_CLAIM
    staff_can_review = request.user.is_staff and (
        contact_request.item_report.scope == ItemReport.Scope.INTERNATIONAL
        or hasattr(contact_request.item_report, "custody_record")
    )
    return render(
        request,
        "contacts/request_detail.html",
        {
            "contact_request": contact_request,
            "conversation": conversation,
            "is_claim": is_claim,
            "claim_answers": contact_request.answers.select_related("question") if is_claim else (),
            "evidence_files": contact_request.evidence_files.all() if is_claim else (),
            "can_review_claim": is_claim and (request.user.pk == contact_request.receiving_user_id or staff_can_review),
            "show_expected_answers": is_claim and (request.user.pk == contact_request.receiving_user_id or staff_can_review),
            "claimant_claim_count": ContactRequest.objects.filter(requesting_user=contact_request.requesting_user, request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM).count() if is_claim else 0,
            "can_start_conversation": (
                conversation is None
                and contact_request.status == ContactRequest.Status.PENDING
                and request.user.pk in (
                    contact_request.requesting_user_id,
                    contact_request.receiving_user_id,
                )
            ),
        },
    )


@verified_university_required
def claim_action(request, pk, action):
    claim = get_object_or_404(ContactRequest.objects.select_related("item_report", "requesting_user", "receiving_user"), pk=pk, request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM)
    _require_report_scope(request.user, claim.item_report)
    if request.method == "POST":
        recent_redirect = _recent_auth_redirect(request)
        if recent_redirect:
            return recent_redirect
    if action == "dispute":
        if request.user.pk != claim.requesting_user_id and not request.user.is_staff:
            raise PermissionDenied
    elif request.user.pk != claim.receiving_user_id and not request.user.is_staff:
        raise PermissionDenied
    if request.method == "POST":
        form = ClarificationForm(request.POST) if action == "request_more" else None
        if form is None or form.is_valid():
            try:
                updated, conversation = OwnershipVerificationService.change_status(
                    claim=claim, actor=request.user, action=action,
                    clarification=form.cleaned_data["clarification"] if form else "",
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, _("The ownership claim was updated."))
                return redirect("conversation_detail", pk=conversation.pk) if conversation else redirect("contact_request_detail", pk=claim.pk)
    elif request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    else:
        form = ClarificationForm() if action == "request_more" else None
    return render(request, "contacts/claim_action_confirm.html", {"claim": claim, "action": action, "form": form})


@verified_university_required
def claim_clarification_answer(request, pk):
    claim = get_object_or_404(ContactRequest, pk=pk, requesting_user=request.user, status=ContactRequest.Status.MORE_INFORMATION)
    _require_report_scope(request.user, claim.item_report)
    form = ClarificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        claim.clarification_answer = form.cleaned_data["clarification"]
        claim.status = ContactRequest.Status.PENDING
        claim.save(update_fields=("clarification_answer", "status"))
        OwnershipVerificationService.audit(claim, request.user, ContactAuditLog.EventType.ADDITIONAL_ANSWER, _("Additional ownership information was submitted."))
        return redirect("contact_request_detail", pk=claim.pk)
    return render(request, "contacts/claim_action_confirm.html", {"claim": claim, "action": "answer", "form": form})


@verified_university_required
def claim_evidence_download(request, pk):
    evidence = get_object_or_404(ClaimEvidence.objects.select_related("contact_request"), pk=pk)
    claim = evidence.contact_request
    _require_report_scope(request.user, claim.item_report)
    if request.user.pk not in (claim.requesting_user_id, claim.receiving_user_id) and not request.user.is_staff:
        raise PermissionDenied
    from django.http import FileResponse
    return FileResponse(evidence.file.open("rb"), as_attachment=True, filename=f"private-evidence-{evidence.pk}{Path(evidence.file.name).suffix}")


@verified_university_required
def claim_report_suspicious(request, pk):
    claim = get_object_or_404(ContactRequest, pk=pk, receiving_user=request.user)
    _require_report_scope(request.user, claim.item_report)
    form = SuspiciousClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        SuspiciousClaimReport.objects.update_or_create(contact_request=claim, defaults={"reported_by": request.user, "reason": form.cleaned_data["reason"]})
        UserBlock.objects.get_or_create(blocker=request.user, blocked_user=claim.requesting_user)
        OwnershipVerificationService.audit(claim, request.user, ContactAuditLog.EventType.SUSPICIOUS_CLAIM, _("A suspicious ownership claim was reported."))
        messages.success(request, _("The suspicious claim was reported and the claimant was blocked."))
        return redirect("contact_request_detail", pk=claim.pk)
    return render(request, "contacts/claim_action_confirm.html", {"claim": claim, "action": "suspicious", "form": form})


@verified_university_required
def claim_appeal(request, pk):
    claim = get_object_or_404(
        ContactRequest.objects.select_related("item_report"), pk=pk,
        requesting_user=request.user, status=ContactRequest.Status.REJECTED,
    )
    _require_report_scope(request.user, claim.item_report)
    if hasattr(claim, "appeal"):
        messages.info(request, _("An appeal already exists for this claim."))
        return redirect("contact_request_detail", pk=claim.pk)
    form = ClaimAppealForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            appeal = form.save(commit=False)
            appeal.contact_request = claim
            appeal.submitted_by = request.user
            appeal.save()
            claim.status = ContactRequest.Status.DISPUTED
            claim.save(update_fields=("status",))
            OwnershipVerificationService.audit(
                claim, request.user, ContactAuditLog.EventType.CLAIM_DISPUTED,
                _("A rejected ownership claim was appealed for administrator review."),
            )
        messages.success(request, _("Your appeal was submitted for administrator review."))
        return redirect("contact_request_detail", pk=claim.pk)
    return render(request, "contacts/claim_action_confirm.html", {
        "claim": claim, "action": "appeal", "form": form,
    })


@verified_university_required
def report_content(request, target_type, pk):
    if target_type == ContentReport.TargetType.ITEM_REPORT:
        target = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
        _require_report_scope(request.user, target)
    elif target_type == ContentReport.TargetType.MESSAGE:
        target = get_object_or_404(Message.objects.select_related("conversation__item_report"), pk=pk)
        if not target.conversation.can_view(request.user):
            raise PermissionDenied
        _require_report_scope(request.user, target.conversation.item_report)
    else:
        raise Http404
    form = ContentReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ContentReport.objects.update_or_create(
            reporter=request.user, target_type=target_type, target_identifier=pk,
            status="open", defaults={"reason": form.cleaned_data["reason"]},
        )
        messages.success(request, _("The content was reported for administrator review."))
        if target_type == ContentReport.TargetType.MESSAGE:
            return redirect("conversation_detail", pk=target.conversation_id)
        return redirect(target)
    return render(request, "contacts/claim_action_confirm.html", {
        "action": "report_content", "form": form, "target": target,
    })


@verified_university_required
def dismiss_match(request, lost_pk, found_pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lost = get_object_or_404(ItemReport, pk=lost_pk, report_type=ItemReport.ReportType.LOST)
    found = get_object_or_404(ItemReport, pk=found_pk, report_type=ItemReport.ReportType.FOUND)
    if request.user.pk not in (lost.owner_id, found.owner_id) and not request.user.is_staff:
        raise PermissionDenied
    _require_report_scope(request.user, lost)
    if lost.scope != found.scope:
        raise PermissionDenied
    DismissedMatch.objects.get_or_create(user=request.user, lost_report=lost, found_report=found)
    messages.success(request, _("The possible match was dismissed for your account."))
    owned = lost if lost.owner_id == request.user.pk else found
    return redirect("item_matches", pk=owned.pk)


@verified_university_required
def claim_handover_confirm(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    claim = get_object_or_404(ContactRequest, pk=pk)
    _require_report_scope(request.user, claim.item_report)
    completed = OwnershipVerificationService.confirm_handover(claim=claim, user=request.user)
    messages.success(request, _("Handover completed and the report was resolved.") if completed else _("Your confirmation was saved. Awaiting the other participant's confirmation."))
    return redirect("contact_request_detail", pk=claim.pk)


@verified_university_required
def contact_request_start(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    contact_request = get_object_or_404(
        ContactRequest.objects.select_related("item_report", "requesting_user", "receiving_user"),
        pk=pk,
        status=ContactRequest.Status.PENDING,
    )
    _require_report_scope(request.user, contact_request.item_report)
    if request.user.pk not in (
        contact_request.requesting_user_id,
        contact_request.receiving_user_id,
    ):
        raise PermissionDenied
    try:
        conversation, conversation_created = ConversationInitiationService.start(
            item_report=contact_request.item_report,
            initiating_user=contact_request.requesting_user,
            initial_message=contact_request.initial_message,
            actor=request.user,
            contact_request=contact_request,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("contact_request_detail", pk=contact_request.pk)
    messages.success(request, _("The private conversation is now active."))
    return redirect("conversation_detail", pk=conversation.pk)


@verified_university_required
def contact_request_cancel(request, pk):
    contact_request = get_object_or_404(ContactRequest, pk=pk, requesting_user=request.user)
    _require_report_scope(request.user, contact_request.item_report)
    if contact_request.status not in (ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION):
        raise PermissionDenied(_("Only pending requests can be cancelled."))
    if request.method == "POST":
        contact_request.status = ContactRequest.Status.CANCELLED
        contact_request.save(update_fields=["status"])
        record_contact_event(
            actor=request.user,
            event_type=ContactAuditLog.EventType.REQUEST_CANCELLED,
            item_report=contact_request.item_report,
            contact_request=contact_request,
            description=_("A pending contact request was cancelled."),
        )
        messages.success(request, _("The contact request was cancelled."))
        return redirect("contact_requests_sent")
    return render(
        request,
        "contacts/request_action_confirm.html",
        {"contact_request": contact_request, "action": "cancel"},
    )


@verified_university_required
def conversation_list(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    conversations = Conversation.objects.filter(
        Q(first_participant=request.user) | Q(second_participant=request.user)
    ).filter(item_report__scope=active_scope).select_related("item_report", "first_participant", "second_participant")
    for conversation in conversations:
        conversation.display_participant = conversation.other_participant(request.user)
    return render(request, "contacts/conversation_list.html", {"conversations": conversations})


@verified_university_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related(
            "item_report",
            "approved_contact_request",
            "first_participant",
            "second_participant",
        ),
        pk=pk,
    )
    if not conversation.can_view(request.user):
        raise PermissionDenied
    _require_report_scope(request.user, conversation.item_report)
    contact_request = conversation.approved_contact_request
    participant_can_send = request.user.pk in (
        conversation.first_participant_id,
        conversation.second_participant_id,
    )
    permission_active = (
        conversation.is_active
        and conversation.status == Conversation.DealStatus.ACTIVE
    )
    thread_messages = conversation.messages.select_related("sender").order_by("sent_at")
    if request.method == "POST":
        if not participant_can_send or not permission_active:
            raise PermissionDenied(_("This conversation is not available for messaging."))
        profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
        if not request.user.is_staff and not profile.email_verified_at:
            raise PermissionDenied(_("Verify your email address before sending private messages."))
        form = MessageForm(request.POST, request.FILES)
        try:
            RateLimitService.check(request, "message")
        except ValidationError as exc:
            form.add_error(None, exc)
        if form.is_valid():
            message = form.save(commit=False)
            message.conversation = conversation
            message.sender = request.user
            message.full_clean()
            message.save()
            conversation.last_message_at = message.sent_at
            conversation.save(update_fields=["last_message_at"])
            recipient = conversation.other_participant(request.user)
            NotificationService.create(
                recipient=recipient,
                notification_type=Notification.NotificationType.NEW_MESSAGE,
                title=_("New private message"),
                safe_message=_("You have a new message about ‘%(title)s’.") % {"title": conversation.item_report.title},
                conversation=conversation,
                item_report=conversation.item_report,
                destination_url=reverse("conversation_detail", args=[conversation.pk]),
                deduplication_key=f"message:{message.pk}:{recipient.pk}",
            )
            record_contact_event(
                actor=request.user,
                event_type=ContactAuditLog.EventType.MESSAGE_SENT,
                item_report=conversation.item_report,
                contact_request=contact_request,
                conversation=conversation,
                description=_("A conversation message was sent."),
            )
            return redirect("conversation_detail", pk=conversation.pk)
    else:
        form = MessageForm()
    unread_messages = conversation.messages.none()
    if participant_can_send:
        unread_messages = thread_messages.exclude(sender=request.user).filter(
            read_at__isnull=True
        )
    unread_count = unread_messages.count()
    if unread_count:
        unread_messages.update(read_at=timezone.now())
        record_contact_event(
            actor=request.user,
            event_type=ContactAuditLog.EventType.MESSAGE_READ,
            item_report=conversation.item_report,
            contact_request=contact_request,
            conversation=conversation,
            description=_("One or more conversation messages were read."),
        )
    NotificationService.mark_conversation_messages_read(
        recipient=request.user, conversation=conversation
    )
    record_contact_event(
        actor=request.user,
        event_type=ContactAuditLog.EventType.CONVERSATION_OPENED,
        item_report=conversation.item_report,
        contact_request=contact_request,
        conversation=conversation,
        description=_("A private conversation was opened."),
    )
    contact_people = []
    participants = [conversation.first_participant, conversation.second_participant]
    visible_people = participants if request.user.is_staff else [conversation.other_participant(request.user)]
    allow_contact_details = (
        contact_request.request_type != ContactRequest.RequestType.OWNERSHIP_CLAIM
        or not contact_request.truthful_confirmation
    )
    for person in visible_people if permission_active and allow_contact_details else []:
        phone_access = phone_number_access(
            phone_owner=person,
            viewer=request.user,
            contact_request=contact_request,
            conversation=conversation,
        )
        record_contact_event(
            actor=request.user,
            event_type=(
                ContactAuditLog.EventType.PHONE_MASKED
                if phone_access and phone_access.is_masked
                else ContactAuditLog.EventType.PHONE_GRANTED
                if phone_access
                else ContactAuditLog.EventType.PHONE_BLOCKED
            ),
            item_report=conversation.item_report,
            contact_request=contact_request,
            conversation=conversation,
            description=(
                "A masked phone number was displayed under the user's privacy preference."
                if phone_access and phone_access.is_masked
                else "Consent-controlled phone-number access was granted."
                if phone_access
                else "Phone-number access was blocked by consent or permission rules."
            ),
        )
        contact_people.append(
            {
                "user": person,
                "phone_display": phone_access.display_number if phone_access else None,
                "phone_href": phone_access.dial_number if phone_access else None,
                "phone_is_masked": phone_access.is_masked if phone_access else False,
            }
        )
    return render(
        request,
        "contacts/conversation_detail.html",
        {
            "conversation": conversation,
            "thread_messages": thread_messages,
            "form": form,
            "permission_active": permission_active,
            "participant_can_send": participant_can_send,
            "contact_people": contact_people,
            "can_complete": (
                permission_active
                and (
                    (contact_request.request_type == ContactRequest.RequestType.OWNERSHIP_CLAIM and contact_request.truthful_confirmation)
                    or request.user == DealService.receiving_participant(conversation)
                    or request.user.is_staff
                )
            ),
        },
    )


@verified_university_required
def message_delete(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    accessible_messages = Message.objects.select_related("conversation")
    if not request.user.is_staff:
        accessible_messages = accessible_messages.filter(
            Q(conversation__first_participant=request.user)
            | Q(conversation__second_participant=request.user)
        )
    message = get_object_or_404(accessible_messages, pk=pk)
    _require_report_scope(request.user, message.conversation.item_report)
    if message.sender != request.user and not request.user.is_staff:
        raise PermissionDenied
    if not message.conversation.can_view(request.user):
        raise PermissionDenied
    message.is_deleted = True
    message.body = ""
    message.save(update_fields=["is_deleted", "body"])
    messages.success(request, _("The message was removed from the conversation."))
    return redirect("conversation_detail", pk=message.conversation_id)


@verified_university_required
def message_attachment_download(request, pk):
    message = get_object_or_404(Message.objects.select_related("conversation"), pk=pk, attachment__gt="")
    if not message.conversation.can_view(request.user):
        raise PermissionDenied
    _require_report_scope(request.user, message.conversation.item_report)
    from django.http import FileResponse
    return FileResponse(
        message.attachment.open("rb"), as_attachment=True,
        filename=f"message-attachment-{message.pk}{Path(message.attachment.name).suffix}",
    )


@verified_university_required
def report_renew(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    _require_report_scope(request.user, report)
    try:
        ReportLifecycleService.renew(report=report, user=request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, _("The report was renewed and is active again."))
    return redirect("item_detail", pk=report.pk)


@verified_university_required
def change_status(request, pk, new_status):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    _require_report_scope(request.user, report)
    if not can_manage(request.user, report):
        raise PermissionDenied
    allowed = {
        "resolved": ItemReport.Status.RESOLVED,
        "closed": ItemReport.Status.CLOSED,
    }
    if new_status not in allowed:
        raise PermissionDenied(_("Unsupported status change."))
    if new_status == "resolved" and report.scope == ItemReport.Scope.UNIVERSITY and not request.user.is_staff:
        raise PermissionDenied(_("Only authorized staff may mark a University item Returned."))
    if request.method == "POST":
        if request.user.is_staff:
            recent_redirect = _recent_auth_redirect(request)
            if recent_redirect:
                return recent_redirect
        custody = getattr(report, "custody_record", None)
        if new_status == "resolved" and custody:
            if custody.status == CustodyRecord.Status.MISSING or custody.incidents.filter(resolved_at__isnull=True).exists():
                raise PermissionDenied(_("A report with an unresolved custody incident cannot be marked Returned."))
            if report.scope == ItemReport.Scope.UNIVERSITY and custody.status != CustodyRecord.Status.HANDED_OVER:
                raise PermissionDenied(_("Complete the official custody handover before marking this report Returned."))
        report.status = allowed[new_status]
        report.save(update_fields=["status", "updated_at"])
        messages.success(request, _("The report is now %(status)s.") % {"status": report.get_status_display().lower()})
        return redirect(report)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    return render(
        request,
        "items/report_status_confirm.html",
        {"report": report, "new_status": new_status},
    )


@verified_university_required
def report_delete(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    _require_report_scope(request.user, report)
    if not can_manage(request.user, report):
        raise PermissionDenied
    if request.method == "POST":
        report.is_deleted = True
        report.is_hidden = True
        report.deleted_at = timezone.now()
        report.deleted_by = request.user
        report.save(
            update_fields=["is_deleted", "is_hidden", "deleted_at", "deleted_by", "updated_at"]
        )
        messages.success(request, _("The report was removed from public and matching pages."))
        return redirect("management_reports" if request.user.is_staff else "my_reports")
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    return render(
        request,
        "items/report_delete_confirm.html",
        {"report": report, "cancel_url": report.get_absolute_url()},
    )


def require_staff(request):
    if not request.user.is_authenticated:
        return redirect(f'{reverse("login")}?next={request.get_full_path()}')
    if not request.user.is_staff:
        raise PermissionDenied(_("This area is available only to staff accounts."))
    return None


def dashboard_home(request):
    denied = require_staff(request)
    if denied:
        return denied
    active_reports = ItemReport.objects.filter(is_deleted=False)
    context = {
        "total_users": User.objects.count(),
        "total_lost": active_reports.filter(report_type=ItemReport.ReportType.LOST).count(),
        "total_found": active_reports.filter(report_type=ItemReport.ReportType.FOUND).count(),
        "total_resolved": active_reports.filter(status=ItemReport.Status.RESOLVED).count(),
        "recent_reports": active_reports.select_related("owner")[:8],
        "university_reports": active_reports.filter(scope=ItemReport.Scope.UNIVERSITY).count(),
        "international_reports": active_reports.filter(scope=ItemReport.Scope.INTERNATIONAL).count(),
        "pending_claims": ContactRequest.objects.filter(status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION)).count(),
        "disputed_claims": ContactRequest.objects.filter(status=ContactRequest.Status.DISPUTED).count(),
    }
    return render(request, "dashboard/home.html", context)


def dashboard_reports(request):
    denied = require_staff(request)
    if denied:
        return denied
    reports = ItemReport.objects.select_related("owner").all()
    form = AdminReportFilterForm(request.GET)
    if form.is_valid():
        data = form.cleaned_data
        if data["query"]:
            reports = reports.filter(
                Q(title__icontains=data["query"])
                | Q(description__icontains=data["query"])
                | Q(owner__username__icontains=data["query"])
            )
        for field in (
            "scope", "report_type", "category", "item_type", "primary_colour", "brand", "material",
            "approximate_size", "campus_location", "university_location", "status", "country", "region",
            "city", "district", "place_type", "place_name",
        ):
            if data.get(field):
                lookup = field if field in {
                    "scope", "report_type", "category", "item_type", "primary_colour", "brand",
                    "material", "approximate_size", "campus_location", "university_location",
                    "status", "place_type",
                } else f"{field}__iexact"
                reports = reports.filter(**{lookup: data[field]})
        if data["date_from"]:
            reports = reports.filter(item_date__gte=data["date_from"])
        if data["date_to"]:
            reports = reports.filter(item_date__lte=data["date_to"])
        if data["visibility"]:
            reports = reports.filter(is_hidden=data["visibility"] == "hidden")
        reports = reports.order_by({"oldest": "created_at", "closest_date": "-item_date"}.get(data.get("sort"), "-created_at"))
    paginator = Paginator(reports, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "dashboard/report_list.html",
        {
            "form": form,
            "page_obj": page_obj,
            "query_string": query_params.urlencode(),
            "bulk_actions": AdminReportActionService.ACTION_LABELS,
        },
    )


def dashboard_report_visibility(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    report.is_hidden = not report.is_hidden
    report.save(update_fields=["is_hidden", "updated_at"])
    state = _("hidden from public pages") if report.is_hidden else _("visible again")
    messages.success(request, _("“%(title)s” is now %(state)s.") % {"title": report.title, "state": state})
    return redirect("management_reports")


def _selected_reports(request):
    report_ids = request.POST.getlist("report_ids[]") or request.POST.getlist("report_ids")
    valid_ids = []
    for value in report_ids:
        try:
            valid_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return valid_ids, ItemReport.objects.filter(pk__in=valid_ids).select_related("owner")


def dashboard_report_bulk_action(request):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    action = request.POST.get("action", "")
    selected_ids, reports = _selected_reports(request)
    if action not in AdminReportActionService.ACTION_LABELS:
        messages.error(request, _("Choose a valid bulk action."))
        return redirect("management_reports")
    if not selected_ids:
        messages.error(request, _("Select at least one report."))
        return redirect("management_reports")
    if action in AdminReportActionService.CONFIRMATION_ACTIONS:
        return render(
            request,
            "dashboard/report_bulk_confirm.html",
            {
                "reports": reports,
                "report_ids": selected_ids,
                "action": action,
                "action_label": AdminReportActionService.ACTION_LABELS[action],
            },
        )
    return _apply_bulk_report_action(request, action, selected_ids, reports)


def dashboard_report_bulk_confirm(request):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    action = request.POST.get("action", "")
    selected_ids, reports = _selected_reports(request)
    if action not in AdminReportActionService.CONFIRMATION_ACTIONS or not selected_ids:
        messages.error(request, _("The bulk-action confirmation was invalid or expired."))
        return redirect("management_reports")
    return _apply_bulk_report_action(request, action, selected_ids, reports)


def _apply_bulk_report_action(request, action, selected_ids, reports):
    result = AdminReportActionService.apply(
        administrator=request.user, reports=reports, action=action
    )
    missing = len(set(selected_ids)) - reports.count()
    result.skipped_count += max(missing, 0)
    messages.success(
        request,
        _("%(updated)s report(s) updated; %(skipped)s skipped.") % {
            "updated": result.success_count,
            "skipped": result.skipped_count,
        },
    )
    for reason in result.skipped_reasons:
        messages.warning(request, reason)
    return redirect("management_reports")


def dashboard_users(request):
    denied = require_staff(request)
    if denied:
        return denied
    users = User.objects.annotate(report_count=models.Count("item_reports")).order_by("username")
    form = AdminUserFilterForm(request.GET)
    if form.is_valid():
        data = form.cleaned_data
        if data["query"]:
            users = users.filter(
                Q(username__icontains=data["query"]) | Q(email__icontains=data["query"])
            )
        if data["account_type"]:
            users = users.filter(is_staff=data["account_type"] == "staff")
        if data["account_status"]:
            users = users.filter(is_active=data["account_status"] == "active")
    return render(request, "dashboard/user_list.html", {"form": form, "users": users})


def dashboard_user_detail(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    managed_user = get_object_or_404(User, pk=pk)
    return render(
        request,
        "dashboard/user_detail.html",
        {"managed_user": managed_user, "reports": managed_user.item_reports.all(), "status_form": AdminUserStatusForm()},
    )


def dashboard_user_toggle_active(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    managed_user = get_object_or_404(User, pk=pk)
    if managed_user == request.user or managed_user.is_superuser:
        messages.error(request, _("This administrator account cannot be deactivated here."))
    else:
        form = AdminUserStatusForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("A reason is required for this account action."))
            return redirect("management_user_detail", pk=managed_user.pk)
        managed_user.is_active = not managed_user.is_active
        managed_user.save(update_fields=["is_active"])
        ContactAuditLog.objects.create(
            acting_user=request.user,
            event_type=(ContactAuditLog.EventType.USER_RESTORED if managed_user.is_active else ContactAuditLog.EventType.USER_SUSPENDED),
            item_report=None,
            description=_("An administrator changed a user account status after recording a private reason."),
        )
        messages.success(request, _("Account “%(username)s” was updated.") % {"username": managed_user.username})
    return redirect("management_user_detail", pk=managed_user.pk)


def management_conversations(request):
    denied = require_staff(request)
    if denied:
        return denied
    conversations = Conversation.objects.select_related(
        "item_report", "approved_contact_request", "first_participant", "second_participant"
    )
    return render(
        request, "dashboard/conversation_list.html", {"conversations": conversations}
    )


def management_conversation_deactivate(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    conversation = get_object_or_404(Conversation, pk=pk)
    if request.method == "POST" and conversation.status != Conversation.DealStatus.ACTIVE:
        raise PermissionDenied(_("Only active conversations can be deactivated."))
    form = ConversationDeactivateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        now = timezone.now()
        reason = form.cleaned_data["reason"]
        conversation.is_active = False
        conversation.status = Conversation.DealStatus.DEACTIVATED
        conversation.deactivated_at = now
        conversation.deactivated_by = request.user
        conversation.deactivation_reason = reason
        conversation.save(update_fields=[
            "is_active", "status", "deactivated_at", "deactivated_by",
            "deactivation_reason",
        ])
        record_contact_event(
            actor=request.user,
            event_type=ContactAuditLog.EventType.CONVERSATION_DEACTIVATED,
            item_report=conversation.item_report,
            contact_request=conversation.approved_contact_request,
            conversation=conversation,
            description=_("An administrator deactivated a conversation after recording a private reason."),
        )
        destination = reverse("conversation_detail", args=[conversation.pk])
        for participant in (conversation.first_participant, conversation.second_participant):
            NotificationService.create(
                recipient=participant,
                notification_type=Notification.NotificationType.CONVERSATION_DEACTIVATED,
                title=_("Conversation deactivated"),
                safe_message=_("The conversation about ‘%(title)s’ was deactivated by an administrator.") % {"title": conversation.item_report.title},
                conversation=conversation,
                item_report=conversation.item_report,
                destination_url=destination,
                deduplication_key=f"conversation-deactivated:{conversation.pk}:{participant.pk}:{now.isoformat()}",
            )
        messages.success(request, _("The conversation was deactivated."))
        return redirect("management_conversations")
    return render(
        request,
        "dashboard/conversation_deactivate_confirm.html",
        {"conversation": conversation, "form": form},
    )


@verified_university_required
def conversation_complete(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related(
            "item_report", "approved_contact_request", "first_participant", "second_participant"
        ),
        pk=pk,
    )
    if not conversation.can_view(request.user):
        raise PermissionDenied
    _require_report_scope(request.user, conversation.item_report)
    is_ownership_claim = (
        conversation.approved_contact_request.request_type == ContactRequest.RequestType.OWNERSHIP_CLAIM
        and conversation.approved_contact_request.truthful_confirmation
    )
    if not is_ownership_claim and request.user != DealService.receiving_participant(conversation):
        raise PermissionDenied(_("Only the receiving participant can complete this deal."))
    if is_ownership_claim:
        if request.method == "POST":
            completed = OwnershipVerificationService.confirm_handover(
                claim=conversation.approved_contact_request, user=request.user
            )
            messages.success(request, _("Handover completed and the report was resolved.") if completed else _("Your confirmation was saved. Awaiting the other participant's confirmation."))
            return redirect("conversation_detail", pk=conversation.pk)
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])
        return render(request, "contacts/conversation_complete_confirm.html", {"conversation": conversation, "ownership_confirmation": True})
    return _complete_conversation(request, conversation, allow_staff=False)


def management_conversation_complete(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    conversation = get_object_or_404(Conversation, pk=pk)
    return _complete_conversation(request, conversation, allow_staff=True)


def _complete_conversation(request, conversation, allow_staff):
    if request.method == "POST":
        try:
            completed_conversation, changed = DealService.complete(
                conversation=conversation, acting_user=request.user, allow_staff=allow_staff
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("The deal was completed and the report resolved.")
                if changed else _("This deal was already completed."),
            )
        return redirect("conversation_detail", pk=conversation.pk)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    return render(
        request,
        "contacts/conversation_complete_confirm.html",
        {"conversation": conversation, "management_action": allow_staff},
    )


def management_conversation_reopen(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    conversation = get_object_or_404(Conversation, pk=pk)
    form = ConversationReopenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            DealService.reopen(
                conversation=conversation,
                administrator=request.user,
                reason=form.cleaned_data["reason"],
                change_report_status=form.cleaned_data["change_report_status"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, _("The conversation was reopened."))
            return redirect("management_conversations")
    return render(
        request,
        "dashboard/conversation_reopen.html",
        {"conversation": conversation, "form": form},
    )


@verified_university_required
def notification_list(request):
    notifications = request.user.notifications.filter(
        Q(item_report__isnull=True) | Q(item_report__scope__in=UniversityAccessService.accessible_scopes(request.user))
    ).select_related("conversation", "item_report")
    paginator = Paginator(notifications, 30)
    return render(
        request, "notifications/list.html", {"page_obj": paginator.get_page(request.GET.get("page"))}
    )


@verified_university_required
def notification_unread_count(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    visible = request.user.notifications.filter(
        Q(item_report__isnull=True) | Q(item_report__scope__in=UniversityAccessService.accessible_scopes(request.user))
    )
    notifications = visible.filter(is_read=False)[:6]
    return JsonResponse(
        {
            "unread_count": visible.filter(is_read=False).count(),
            "notifications": [
                {
                    "id": notification.pk,
                    "title": notification.title,
                    "message": notification.safe_message,
                    "url": notification.destination_url,
                    "created_at": notification.created_at.isoformat(),
                }
                for notification in notifications
            ],
        }
    )


@verified_university_required
def notification_mark_read(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    if notification.destination_url.startswith("/") and not notification.destination_url.startswith("//"):
        return redirect(notification.destination_url)
    return redirect("notification_list")


@verified_university_required
def notification_mark_all_read(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect("notification_list")


def management_audit_log(request):
    denied = require_staff(request)
    if denied:
        return denied
    audit_events = ContactAuditLog.objects.select_related(
        "acting_user", "item_report", "contact_request", "conversation"
    )
    return render(request, "dashboard/audit_log.html", {"audit_events": audit_events})


def management_claims(request):
    denied = require_staff(request)
    if denied:
        return denied
    claims = ContactRequest.objects.filter(
        request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM
    ).select_related("item_report", "requesting_user", "receiving_user")
    status = request.GET.get("status", "")
    scope = request.GET.get("scope", "")
    if status in ContactRequest.Status.values:
        claims = claims.filter(status=status)
    if scope in ItemReport.Scope.values:
        claims = claims.filter(item_report__scope=scope)
    return render(request, "dashboard/claim_list.html", {
        "claims": claims, "appeals": ClaimAppeal.objects.select_related(
            "contact_request__item_report", "submitted_by", "reviewed_by"
        ), "selected_status": status, "selected_scope": scope,
    })


def management_appeal_action(request, pk, action):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    if action not in {"uphold", "deny"}:
        raise Http404
    appeal = get_object_or_404(
        ClaimAppeal.objects.select_related("contact_request"), pk=pk,
        status=ClaimAppeal.Status.PENDING,
    )
    with transaction.atomic():
        appeal.status = ClaimAppeal.Status.UPHELD if action == "uphold" else ClaimAppeal.Status.DENIED
        appeal.reviewed_at = timezone.now()
        appeal.reviewed_by = request.user
        appeal.save(update_fields=("status", "reviewed_at", "reviewed_by"))
        claim = appeal.contact_request
        claim.status = ContactRequest.Status.PENDING if action == "uphold" else ContactRequest.Status.REJECTED
        claim.reviewed_at = timezone.now()
        claim.reviewed_by = request.user
        claim.save(update_fields=("status", "reviewed_at", "reviewed_by"))
    messages.success(request, _("The claim appeal was reviewed."))
    return redirect("management_claims")


def management_moderation(request):
    denied = require_staff(request)
    if denied:
        return denied
    content_reports = ContentReport.objects.select_related("reporter")
    return render(request, "dashboard/moderation.html", {"content_reports": content_reports})


def management_moderation_action(request, pk, action):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    content_report = get_object_or_404(ContentReport, pk=pk)
    if action == "hide" and content_report.target_type == ContentReport.TargetType.ITEM_REPORT:
        target = get_object_or_404(ItemReport, pk=content_report.target_identifier)
        target.is_hidden = True
        target.save(update_fields=("is_hidden", "updated_at"))
    elif action == "hide" and content_report.target_type == ContentReport.TargetType.MESSAGE:
        target = get_object_or_404(Message, pk=content_report.target_identifier)
        target.is_deleted = True
        target.body = ""
        target.save(update_fields=("is_deleted", "body"))
    elif action != "close":
        raise Http404
    content_report.status = "closed"
    content_report.reviewed_at = timezone.now()
    content_report.save(update_fields=("status", "reviewed_at"))
    messages.success(request, _("The moderation report was reviewed."))
    return redirect("management_moderation")


def management_locations(request):
    denied = require_staff(request)
    if denied:
        return denied
    form = UniversityLocationForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "create" and form.is_valid():
        form.save()
        messages.success(request, _("The University location was added."))
        return redirect("management_locations")
    return render(request, "dashboard/location_list.html", {
        "form": form, "locations": UniversityLocation.objects.all(),
    })


def management_location_toggle(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    location = get_object_or_404(UniversityLocation, pk=pk)
    location.is_active = not location.is_active
    location.save(update_fields=("is_active",))
    messages.success(request, _("The University location availability was updated."))
    return redirect("management_locations")


def management_custody(request):
    denied = require_staff(request)
    if denied:
        return denied
    form = CustodyRecordForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "create" and form.is_valid():
        with transaction.atomic():
            record = form.save(commit=False)
            record.received_by = request.user
            record.full_clean()
            record.save()
            CustodyMovement.objects.create(
                custody_record=record, event_type="intake", recorded_by=request.user,
                safe_note="Item received into University custody.",
            )
        messages.success(request, _("The custody record was created."))
        return redirect("management_custody")
    records = CustodyRecord.objects.select_related("found_report", "received_by", "handover_staff")
    return render(request, "dashboard/custody.html", {
        "records": records, "form": form,
        "approaching_retention": records.filter(
            retention_expires_at__lte=timezone.now() + timedelta(days=14),
            status__in=(CustodyRecord.Status.RECEIVED, CustodyRecord.Status.STORED),
        ),
    })


def management_custody_incident(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    record = get_object_or_404(CustodyRecord, pk=pk)
    form = StorageIncidentForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            StorageIncident.objects.create(
                custody_record=record, reported_by=request.user, summary=form.cleaned_data["summary"]
            )
            record.status = CustodyRecord.Status.MISSING
            record.save(update_fields=("status", "updated_at"))
            CustodyMovement.objects.create(
                custody_record=record, event_type="incident", recorded_by=request.user,
                safe_note="Missing-in-storage incident opened; normal release is blocked.",
            )
        messages.warning(request, _("The item is marked missing and cannot be released normally."))
    else:
        messages.error(request, _("Enter a safe incident summary."))
    return redirect("management_custody")


def management_custody_action(request, pk, action):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    record = get_object_or_404(
        CustodyRecord.objects.select_related("found_report"), pk=pk
    )
    if record.status == CustodyRecord.Status.MISSING:
        raise PermissionDenied(_("A missing-in-storage item cannot be moved, released, or disposed normally."))
    if action == "movement":
        form = CustodyMovementForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                record = CustodyRecord.objects.select_for_update().get(pk=record.pk)
                new_reference = form.cleaned_data.get("new_storage_reference", "").strip()
                if new_reference:
                    record.storage_reference = new_reference
                    record.status = CustodyRecord.Status.STORED
                    record.save(update_fields=("storage_reference", "status", "updated_at"))
                CustodyMovement.objects.create(
                    custody_record=record, event_type=form.cleaned_data["event_type"],
                    recorded_by=request.user, safe_note=form.cleaned_data.get("safe_note", ""),
                )
            messages.success(request, _("The append-only custody movement was recorded."))
        else:
            messages.error(request, _("The custody movement could not be recorded."))
    elif action == "release":
        form = CustodyReleaseForm(
            request.POST, acting_user=request.user, custody_record=record
        )
        claim = record.found_report.contact_requests.filter(
            request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM,
            status__in=(ContactRequest.Status.APPROVED, ContactRequest.Status.RETURN_IN_PROGRESS),
        ).select_related("requesting_user", "receiving_user").first()
        if not claim:
            messages.error(request, _("Approve an ownership claim before releasing this item."))
        elif form.is_valid():
            now = timezone.now()
            with transaction.atomic():
                record = CustodyRecord.objects.select_for_update().get(pk=record.pk)
                if record.incidents.filter(resolved_at__isnull=True).exists():
                    raise PermissionDenied(_("Resolve the storage incident before any release."))
                record.status = CustodyRecord.Status.HANDED_OVER
                record.handover_staff = request.user
                record.handed_over_at = now
                record.recipient_confirmed_at = now
                record.second_release_staff = form.cleaned_data.get("second_staff")
                record.full_clean()
                record.save(update_fields=(
                    "status", "handover_staff", "handed_over_at", "recipient_confirmed_at",
                    "second_release_staff", "updated_at",
                ))
                CustodyMovement.objects.create(
                    custody_record=record, event_type="release", recorded_by=request.user,
                    safe_note=_("Authorized University handover recorded."),
                )
                claim.status = ContactRequest.Status.COMPLETED
                claim.reviewed_at = now
                claim.reviewed_by = request.user
                claim.save(update_fields=("status", "reviewed_at", "reviewed_by"))
                report = ItemReport.objects.select_for_update().get(pk=record.found_report_id)
                report.status = ItemReport.Status.RESOLVED
                report.save(update_fields=("status", "updated_at"))
                ContactRequest.objects.filter(
                    item_report=report,
                    status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION),
                ).exclude(pk=claim.pk).update(status=ContactRequest.Status.CANCELLED, reviewed_at=now)
                if hasattr(claim, "conversation"):
                    conversation = claim.conversation
                    conversation.status = Conversation.DealStatus.COMPLETED
                    conversation.is_active = False
                    conversation.completed_at = now
                    conversation.completed_by = request.user
                    conversation.save(update_fields=(
                        "status", "is_active", "completed_at", "completed_by"
                    ))
                NotificationService.create(
                    recipient=claim.requesting_user,
                    notification_type=Notification.NotificationType.RETURN_UPDATED,
                    title=_("University handover completed"),
                    safe_message=_("Authorized staff recorded the official item return."),
                    item_report=report, destination_url=report.get_absolute_url(),
                    deduplication_key=f"custody-release:{record.pk}:{claim.requesting_user_id}",
                )
            messages.success(request, _("The official handover was recorded and the report is Returned."))
        else:
            messages.error(request, _("Complete the required release confirmations."))
    elif action == "disposition":
        if not request.user.is_superuser:
            raise PermissionDenied(_("Only an authorized administrator may record a final disposition."))
        form = CustodyDispositionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                record = CustodyRecord.objects.select_for_update().get(pk=record.pk)
                record.status = CustodyRecord.Status.DISPOSED
                record.disposition = form.cleaned_data["disposition"]
                record.disposition_at = timezone.now()
                record.disposition_decided_by = request.user
                record.save(update_fields=(
                    "status", "disposition", "disposition_at", "disposition_decided_by", "updated_at"
                ))
                CustodyMovement.objects.create(
                    custody_record=record, event_type="disposition", recorded_by=request.user,
                    safe_note=form.cleaned_data.get("safe_note", ""),
                )
            messages.success(request, _("The authorized University disposition was recorded."))
        else:
            messages.error(request, _("Choose an authorized disposition."))
    else:
        raise Http404
    return redirect("management_custody")


def management_incident_resolve(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    recent_redirect = _recent_auth_redirect(request)
    if recent_redirect:
        return recent_redirect
    incident = get_object_or_404(StorageIncident.objects.select_related("custody_record"), pk=pk, resolved_at__isnull=True)
    if incident.reported_by_id == request.user.pk and not request.user.is_superuser:
        raise PermissionDenied(_("A different supervisor or administrator must review this incident."))
    with transaction.atomic():
        incident.resolved_at = timezone.now()
        incident.reviewed_by = request.user
        incident.save(update_fields=("resolved_at", "reviewed_by"))
        record = incident.custody_record
        if not record.incidents.filter(resolved_at__isnull=True).exclude(pk=incident.pk).exists():
            record.status = CustodyRecord.Status.STORED
            record.save(update_fields=("status", "updated_at"))
        CustodyMovement.objects.create(
            custody_record=record, event_type="review", recorded_by=request.user,
            safe_note=_("Storage incident reviewed and closed by an authorized second reviewer."),
        )
    messages.success(request, _("The storage incident was reviewed and closed."))
    return redirect("management_custody")


def verify_email(request, token):
    try:
        user = EmailVerificationService.verify(token, User)
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist, KeyError):
        messages.error(request, _("This email-verification link is invalid or has expired."))
    else:
        messages.success(request, _("Your email address is verified."))
        if request.user.is_anonymous:
            login(request, user)
    return redirect("profile")


@login_required
def resend_verification(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    if not profile.email_verified_at:
        EmailVerificationService.send(request, request.user)
    messages.success(request, _("If verification is still required, a new link has been sent."))
    return redirect("profile")


@verified_university_required
def return_arrangement(request, pk):
    claim = get_object_or_404(
        ContactRequest.objects.select_related("item_report", "requesting_user", "receiving_user"), pk=pk
    )
    _require_report_scope(request.user, claim.item_report)
    try:
        arrangement = ReturnWorkflowService.get_or_create(claim=claim, user=request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("contact_request_detail", pk=claim.pk)
    form = ReturnArrangementForm(request.POST or None, instance=arrangement, user=request.user)
    if request.method == "POST" and form.is_valid():
        ReturnWorkflowService.update(arrangement=arrangement, user=request.user, form=form)
        messages.success(request, _("The private return arrangement was updated."))
        return redirect("return_arrangement", pk=claim.pk)
    return render(request, "returns/arrangement.html", {"claim": claim, "arrangement": arrangement, "form": form})


@verified_university_required
def return_confirmation(request, pk, role):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    arrangement = get_object_or_404(ReturnArrangement, contact_request_id=pk)
    _require_report_scope(request.user, arrangement.contact_request.item_report)
    ReturnWorkflowService.confirm(arrangement=arrangement, user=request.user, role=role)
    messages.success(request, _("Your return confirmation was recorded."))
    return redirect("return_arrangement", pk=pk)


@verified_university_required
def saved_search_list(request):
    active_scope = getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False))
    return render(request, "alerts/saved_searches.html", {
        "saved_searches": request.user.saved_searches.filter(filters__scope=active_scope),
        "active_scope": active_scope,
    })


@verified_university_required
def saved_search_create(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = SavedSearchForm(request.POST)
    if form.is_valid():
        saved = form.save(commit=False)
        saved.user = request.user
        saved.filters = {
            key: value for key, value in request.POST.items()
            if key in SavedSearch.public_filter_keys() and value
        }
        saved.filters.setdefault("scope", getattr(request, "findmatch_scope", UniversityAccessService.active_scope(request, allow_public=False)))
        saved.full_clean()
        saved.save()
        messages.success(request, _("The search alert was saved."))
    else:
        messages.error(request, _("Choose a unique name for this saved search."))
    return redirect("saved_search_list")


@verified_university_required
def saved_search_action(request, pk, action):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    saved = get_object_or_404(SavedSearch, pk=pk, user=request.user)
    if action == "delete":
        saved.delete()
    elif action in ("pause", "resume"):
        saved.is_active = action == "resume"
        saved.save(update_fields=("is_active", "updated_at"))
    else:
        raise Http404
    return redirect("saved_search_list")


@login_required
def privacy_centre(request):
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/privacy_centre.html", {"profile": profile})


@login_required
def account_data_export(request):
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    data = {
        "account": {"username": request.user.username, "display_name": profile.display_name},
        "reports": list(request.user.item_reports.values("id", "report_type", "title", "status", "created_at")),
        "claims": list(request.user.sent_contact_requests.values("id", "item_report_id", "status", "requested_at")),
        "notification_preferences": {
            "strong_matches": profile.notify_strong_matches,
            "claim_updates": profile.notify_claim_updates,
            "messages": profile.notify_messages,
            "email": profile.email_notifications,
        },
    }
    response = JsonResponse(data, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'attachment; filename="findmatch-account-data.json"'
    return response


@login_required
def request_account_deactivation(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    profile.is_deactivation_requested = True
    profile.deactivation_requested_at = timezone.now()
    profile.save(update_fields=("is_deactivation_requested", "deactivation_requested_at", "updated_at"))
    messages.success(request, _("Your account-deactivation request was recorded for review."))
    return redirect("privacy_centre")


def privacy_policy(request):
    return render(request, "legal/privacy.html")


def terms(request):
    return render(request, "legal/terms.html")


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)

# Create your views here.
