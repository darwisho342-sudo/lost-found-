from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .communications import phone_number_access, record_contact_event
from .forms import (
    AIAssistantRequestForm,
    AIAssistantSettingsForm,
    AdminReportFilterForm,
    AdminCapabilityOverrideForm,
    AdminUserFilterForm,
    ContactRequestForm,
    ConversationDeactivateForm,
    ConversationReopenForm,
    ItemReportForm,
    MessageForm,
    RegistrationForm,
    ReportFilterForm,
    UserProfileForm,
)
from .admin_actions import AdminReportActionService
from .ai_assistant import AIAssistantService, AICapabilityService
from .deals import DealService
from .moderation import SensitiveContentModerationService
from .models import (
    AIAssistantSettings,
    AICapability,
    AICapabilityAuditLog,
    AICapabilitySetting,
    AdminCapabilityOverride,
    ContactAuditLog,
    ContactRequest,
    Conversation,
    ItemReport,
    Message,
    Notification,
    UserBlock,
    UserProfile,
)
from .notification_service import NotificationService
from .conversation_service import ConversationInitiationService
from .services import MatchingService


class RoleAwareLoginView(LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        requested_url = self.get_redirect_url()
        if requested_url:
            return requested_url
        if self.request.user.is_staff:
            return reverse("management_dashboard")
        return reverse("home")


def home(request):
    recent_reports = ItemReport.objects.filter(is_hidden=False, is_deleted=False).select_related("owner")[:6]
    public_reports = ItemReport.objects.filter(is_hidden=False, is_deleted=False)
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
    }
    return render(request, "items/home.html", context)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to FindMatch. Your account is ready.")
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


def report_list(request, report_type=None):
    reports = ItemReport.objects.filter(is_hidden=False, is_deleted=False).select_related("owner")
    filter_data = request.GET.copy()
    if report_type in ItemReport.ReportType.values:
        filter_data["report_type"] = report_type
    form = ReportFilterForm(filter_data)
    if form.is_valid():
        data = form.cleaned_data
        if data["query"]:
            reports = reports.filter(
                Q(title__icontains=data["query"])
                | Q(description__icontains=data["query"])
            )
        for field in ("report_type", "category", "campus_location", "status"):
            if data[field]:
                reports = reports.filter(**{field: data[field]})
        if data["colour"]:
            reports = reports.filter(colour__icontains=data["colour"])
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
            "locked_report_type": report_type,
            "list_title": (
                f"Browse {report_type} items" if report_type else "Browse lost and found items"
            ),
            "clear_url": reverse(
                f"{report_type}_item_list" if report_type else "item_list"
            ),
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


@login_required
def report_create(request, report_type):
    if report_type not in ItemReport.ReportType.values:
        raise PermissionDenied("Unknown report type.")
    form = ItemReportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.owner = request.user
        report.report_type = report_type
        report.save()
        matches = MatchingService.find_matches(report)
        if matches:
            report.status = ItemReport.Status.POSSIBLE_MATCH
            report.save(update_fields=["status", "updated_at"])
        messages.success(request, "Your report was submitted successfully.")
        return redirect("item_matches", pk=report.pk)
    return render(
        request,
        "items/report_form.html",
        {"form": form, "report_type": report_type, "editing": False},
    )


@login_required
def report_edit(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    if not can_manage(request.user, report):
        raise PermissionDenied
    if (
        report.status in [ItemReport.Status.RESOLVED, ItemReport.Status.CLOSED]
        and not request.user.is_staff
    ):
        messages.error(request, "Resolved or closed reports cannot be edited.")
        return redirect(report)
    form = ItemReportForm(request.POST or None, request.FILES or None, instance=report)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your report was updated.")
        return redirect(report)
    return render(
        request,
        "items/report_form.html",
        {"form": form, "report_type": report.report_type, "editing": True},
    )


@login_required
def my_reports(request):
    all_reports = request.user.item_reports.filter(is_deleted=False)
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
    }
    return render(request, "items/my_reports.html", context)


@login_required
def possible_matches(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    if not can_manage(request.user, report):
        raise PermissionDenied
    matches = MatchingService.find_matches(report)
    return render(
        request, "items/possible_matches.html", {"report": report, "matches": matches}
    )


@login_required
def my_possible_matches(request):
    report_groups = []
    reports = request.user.item_reports.filter(
        status__in=[ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH],
        is_deleted=False,
    )
    for report in reports:
        matches = MatchingService.find_matches(report)
        if matches:
            report_groups.append({"report": report, "matches": matches})
    return render(
        request,
        "items/my_possible_matches.html",
        {"report_groups": report_groups},
    )


@login_required
def profile_detail(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/profile.html", {"profile": profile})


@login_required
def profile_edit(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    form = UserProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your contact preferences were updated.")
        return redirect("profile")
    return render(request, "accounts/profile_form.html", {"form": form})


@login_required
def contact_request_create(request, pk):
    item_report = get_object_or_404(ItemReport, pk=pk, is_hidden=False, is_deleted=False)
    form = ContactRequestForm(request.POST or None)
    if request.user == item_report.owner:
        raise PermissionDenied("You cannot contact yourself about your own report.")
    if item_report.status == ItemReport.Status.CLOSED:
        raise PermissionDenied("This report is closed and is not available for contact.")
    if UserBlock.objects.filter(
        blocker=item_report.owner, blocked_user=request.user
    ).exists():
        raise PermissionDenied("You cannot contact this report owner.")
    existing_conversation = ConversationInitiationService.existing_conversation(
        item_report=item_report,
        first_user=request.user,
        second_user=item_report.owner,
    )
    if existing_conversation:
        messages.info(request, "You already have a conversation about this report.")
        return redirect("conversation_detail", pk=existing_conversation.pk)
    if request.method == "POST" and form.is_valid():
        try:
            conversation, created = ConversationInitiationService.start(
                item_report=item_report,
                initiating_user=request.user,
                initial_message=form.cleaned_data["initial_message"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                "Your private conversation was started."
                if created
                else "Your existing conversation was opened.",
            )
            return redirect("conversation_detail", pk=conversation.pk)
    return render(
        request,
        "contacts/request_form.html",
        {
            "form": form,
            "item_report": item_report,
        },
    )


@login_required
def contact_requests_sent(request):
    contact_requests = request.user.sent_contact_requests.select_related(
        "item_report", "receiving_user"
    )
    return render(
        request, "contacts/request_list.html", {"contact_requests": contact_requests, "sent": True}
    )


@login_required
def contact_requests_received(request):
    contact_requests = request.user.received_contact_requests.select_related(
        "item_report", "requesting_user"
    )
    return render(
        request,
        "contacts/request_list.html",
        {"contact_requests": contact_requests, "sent": False},
    )


@login_required
def contact_request_detail(request, pk):
    contact_request = get_object_or_404(
        ContactRequest.objects.select_related(
            "item_report", "requesting_user", "receiving_user", "reviewed_by"
        ),
        pk=pk,
    )
    if not contact_request.can_view(request.user):
        raise PermissionDenied
    conversation = getattr(contact_request, "conversation", None)
    return render(
        request,
        "contacts/request_detail.html",
        {
            "contact_request": contact_request,
            "conversation": conversation,
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


@login_required
def contact_request_start(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    contact_request = get_object_or_404(
        ContactRequest.objects.select_related("item_report", "requesting_user", "receiving_user"),
        pk=pk,
        status=ContactRequest.Status.PENDING,
    )
    if request.user.pk not in (
        contact_request.requesting_user_id,
        contact_request.receiving_user_id,
    ):
        raise PermissionDenied
    try:
        conversation, _ = ConversationInitiationService.start(
            item_report=contact_request.item_report,
            initiating_user=contact_request.requesting_user,
            initial_message=contact_request.initial_message,
            actor=request.user,
            contact_request=contact_request,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("contact_request_detail", pk=contact_request.pk)
    messages.success(request, "The private conversation is now active.")
    return redirect("conversation_detail", pk=conversation.pk)


@login_required
def contact_request_cancel(request, pk):
    contact_request = get_object_or_404(ContactRequest, pk=pk, requesting_user=request.user)
    if contact_request.status != ContactRequest.Status.PENDING:
        raise PermissionDenied("Only pending requests can be cancelled.")
    if request.method == "POST":
        contact_request.status = ContactRequest.Status.CANCELLED
        contact_request.save(update_fields=["status"])
        record_contact_event(
            actor=request.user,
            event_type=ContactAuditLog.EventType.REQUEST_CANCELLED,
            item_report=contact_request.item_report,
            contact_request=contact_request,
            description="A pending contact request was cancelled.",
        )
        messages.success(request, "The contact request was cancelled.")
        return redirect("contact_requests_sent")
    return render(
        request,
        "contacts/request_action_confirm.html",
        {"contact_request": contact_request, "action": "cancel"},
    )


@login_required
def conversation_list(request):
    conversations = Conversation.objects.filter(
        Q(first_participant=request.user) | Q(second_participant=request.user)
    ).select_related("item_report", "first_participant", "second_participant")
    for conversation in conversations:
        conversation.display_participant = conversation.other_participant(request.user)
    return render(request, "contacts/conversation_list.html", {"conversations": conversations})


@login_required
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
            raise PermissionDenied("This conversation is not available for messaging.")
        form = MessageForm(request.POST)
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
                title="New private message",
                safe_message=f"You have a new message about '{conversation.item_report.title}'.",
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
                description="A conversation message was sent.",
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
            description="One or more conversation messages were read.",
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
        description="A private conversation was opened.",
    )
    contact_people = []
    participants = [conversation.first_participant, conversation.second_participant]
    visible_people = participants if request.user.is_staff else [conversation.other_participant(request.user)]
    for person in visible_people if permission_active else []:
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
                    request.user == DealService.receiving_participant(conversation)
                    or request.user.is_staff
                )
            ),
        },
    )


@login_required
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
    if message.sender != request.user and not request.user.is_staff:
        raise PermissionDenied
    if not message.conversation.can_view(request.user):
        raise PermissionDenied
    message.is_deleted = True
    message.body = ""
    message.save(update_fields=["is_deleted", "body"])
    messages.success(request, "The message was removed from the conversation.")
    return redirect("conversation_detail", pk=message.conversation_id)


@login_required
def change_status(request, pk, new_status):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    if not can_manage(request.user, report):
        raise PermissionDenied
    allowed = {
        "resolved": ItemReport.Status.RESOLVED,
        "closed": ItemReport.Status.CLOSED,
    }
    if new_status not in allowed:
        raise PermissionDenied("Unsupported status change.")
    if request.method == "POST":
        report.status = allowed[new_status]
        report.save(update_fields=["status", "updated_at"])
        messages.success(request, f'The report is now {report.get_status_display().lower()}.')
        return redirect(report)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET", "POST"])
    return render(
        request,
        "items/report_status_confirm.html",
        {"report": report, "new_status": new_status},
    )


@login_required
def report_delete(request, pk):
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
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
        messages.success(request, "The report was removed from public and matching pages.")
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
        raise PermissionDenied("This area is available only to staff accounts.")
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
        for field in ("report_type", "category", "campus_location", "status"):
            if data[field]:
                reports = reports.filter(**{field: data[field]})
        if data["colour"]:
            reports = reports.filter(colour__icontains=data["colour"])
        if data["visibility"]:
            reports = reports.filter(is_hidden=data["visibility"] == "hidden")
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
    report = get_object_or_404(ItemReport, pk=pk, is_deleted=False)
    report.is_hidden = not report.is_hidden
    report.save(update_fields=["is_hidden", "updated_at"])
    state = "hidden from public pages" if report.is_hidden else "visible again"
    messages.success(request, f'“{report.title}” is now {state}.')
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
        messages.error(request, "Choose a valid bulk action.")
        return redirect("management_reports")
    if not selected_ids:
        messages.error(request, "Select at least one report.")
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
    action = request.POST.get("action", "")
    selected_ids, reports = _selected_reports(request)
    if action not in AdminReportActionService.CONFIRMATION_ACTIONS or not selected_ids:
        messages.error(request, "The bulk-action confirmation was invalid or expired.")
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
        f"{result.success_count} report(s) updated; {result.skipped_count} skipped.",
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
        {"managed_user": managed_user, "reports": managed_user.item_reports.all()},
    )


def dashboard_user_toggle_active(request, pk):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    managed_user = get_object_or_404(User, pk=pk)
    if managed_user == request.user or managed_user.is_superuser:
        messages.error(request, "This administrator account cannot be deactivated here.")
    else:
        managed_user.is_active = not managed_user.is_active
        managed_user.save(update_fields=["is_active"])
        messages.success(request, f'Account “{managed_user.username}” was updated.')
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
        raise PermissionDenied("Only active conversations can be deactivated.")
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
            description=f"Conversation deactivated. Reason: {reason[:210]}",
        )
        destination = reverse("conversation_detail", args=[conversation.pk])
        for participant in (conversation.first_participant, conversation.second_participant):
            NotificationService.create(
                recipient=participant,
                notification_type=Notification.NotificationType.CONVERSATION_DEACTIVATED,
                title="Conversation deactivated",
                safe_message=f"The conversation about '{conversation.item_report.title}' was deactivated by an administrator.",
                conversation=conversation,
                item_report=conversation.item_report,
                destination_url=destination,
                deduplication_key=f"conversation-deactivated:{conversation.pk}:{participant.pk}:{now.isoformat()}",
            )
        messages.success(request, "The conversation was deactivated.")
        return redirect("management_conversations")
    return render(
        request,
        "dashboard/conversation_deactivate_confirm.html",
        {"conversation": conversation, "form": form},
    )


@login_required
def conversation_complete(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related(
            "item_report", "approved_contact_request", "first_participant", "second_participant"
        ),
        pk=pk,
    )
    if not conversation.can_view(request.user):
        raise PermissionDenied
    if request.user != DealService.receiving_participant(conversation):
        raise PermissionDenied("Only the receiving participant can complete this deal.")
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
            _, changed = DealService.complete(
                conversation=conversation, acting_user=request.user, allow_staff=allow_staff
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                "The deal was completed and the report resolved."
                if changed else "This deal was already completed.",
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
            messages.success(request, "The conversation was reopened.")
            return redirect("management_conversations")
    return render(
        request,
        "dashboard/conversation_reopen.html",
        {"conversation": conversation, "form": form},
    )


@login_required
def notification_list(request):
    notifications = request.user.notifications.select_related("conversation", "item_report")
    paginator = Paginator(notifications, 30)
    return render(
        request, "notifications/list.html", {"page_obj": paginator.get_page(request.GET.get("page"))}
    )


@login_required
def notification_unread_count(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    notifications = request.user.notifications.filter(is_read=False)[:6]
    return JsonResponse(
        {
            "unread_count": request.user.notifications.filter(is_read=False).count(),
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


@login_required
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


@login_required
def notification_mark_all_read(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect("notification_list")


def management_ai_assistant(request):
    denied = require_staff(request)
    if denied:
        return denied
    assistant_settings = AIAssistantSettings.get_solo()
    result = None
    override_form = AdminCapabilityOverrideForm(
        request.POST if request.method == "POST" and request.POST.get("form_action") == "override" else None
    )
    assistant_form = AIAssistantRequestForm(
        request.POST if request.method == "POST" and request.POST.get("form_action") == "execute" else None,
        user=request.user,
    )
    if request.method == "POST" and request.POST.get("form_action") == "override":
        if override_form.is_valid():
            try:
                AICapabilityService.update_override(
                    user=request.user,
                    capability=override_form.cleaned_data["capability"],
                    setting=override_form.cleaned_data["setting"],
                    request=request,
                )
            except ValidationError as exc:
                override_form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(request, "Your capability preference was updated.")
                return redirect("management_ai_assistant")
    elif request.method == "POST":
        if not assistant_settings.is_enabled:
            AICapabilityService.audit(
                user=request.user,
                event_type=AICapabilityAuditLog.EventType.REQUEST_BLOCKED,
                description="An assistant request was blocked because the master setting is disabled.",
                request=request,
            )
            return render(
                request,
                "dashboard/ai_assistant.html",
                {
                    "assistant_settings": assistant_settings,
                    "assistant_form": assistant_form,
                    "override_form": override_form,
                    "result": None,
                    "can_manage_settings": AICapabilityService.can_manage_global_settings(request.user),
                    "overrides": request.user.ai_capability_overrides.select_related("capability"),
                },
                status=403,
            )
        if assistant_form.is_valid():
            try:
                result = AIAssistantService.execute(
                    user=request.user,
                    capability_code=assistant_form.cleaned_data["capability"],
                    input_text=assistant_form.cleaned_data.get("input_text", ""),
                    reports=assistant_form.cleaned_data.get("reports") or (),
                    conversation=assistant_form.cleaned_data.get("conversation"),
                    request=request,
                )
            except ValidationError as exc:
                assistant_form.add_error(None, "; ".join(exc.messages))
    return render(
        request,
        "dashboard/ai_assistant.html",
        {
            "assistant_settings": assistant_settings,
            "assistant_form": assistant_form,
            "override_form": override_form,
            "result": result,
            "can_manage_settings": AICapabilityService.can_manage_global_settings(request.user),
            "overrides": request.user.ai_capability_overrides.select_related("capability"),
        },
    )


def management_ai_assistant_settings(request):
    denied = require_staff(request)
    if denied:
        return denied
    if not AICapabilityService.can_manage_global_settings(request.user):
        raise PermissionDenied("You do not have permission to change global AI Assistant settings.")
    assistant_settings = AIAssistantSettings.get_solo()
    old_master_value = assistant_settings.is_enabled
    old_capability_values = dict(
        AICapabilitySetting.objects.values_list("capability_id", "is_enabled")
    )
    form = AIAssistantSettingsForm(request.POST or None, instance=assistant_settings)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            updated_settings = form.save(commit=False)
            updated_settings.updated_by = request.user
            updated_settings.save()
            enabled_ids = set(form.cleaned_data["enabled_capabilities"].values_list("pk", flat=True))
            for capability in AICapability.objects.all():
                enabled = capability.pk in enabled_ids
                capability_setting, _ = AICapabilitySetting.objects.get_or_create(
                    capability=capability,
                    defaults={"is_enabled": enabled, "updated_by": request.user},
                )
                previous = old_capability_values.get(capability.pk, capability_setting.is_enabled)
                if capability_setting.is_enabled != enabled or capability_setting.updated_by_id != request.user.pk:
                    capability_setting.is_enabled = enabled
                    capability_setting.updated_by = request.user
                    capability_setting.save(update_fields=["is_enabled", "updated_by", "updated_at"])
                if previous != enabled:
                    AICapabilityService.audit(
                        user=request.user,
                        capability=capability,
                        event_type=(
                            AICapabilityAuditLog.EventType.CAPABILITY_ENABLED
                            if enabled
                            else AICapabilityAuditLog.EventType.CAPABILITY_DISABLED
                        ),
                        old_value=previous,
                        new_value=enabled,
                        scope="global",
                        description="A global AI Assistant capability setting changed.",
                        request=request,
                    )
            if old_master_value != updated_settings.is_enabled:
                AICapabilityService.audit(
                    user=request.user,
                    event_type=(
                        AICapabilityAuditLog.EventType.ASSISTANT_ENABLED
                        if updated_settings.is_enabled
                        else AICapabilityAuditLog.EventType.ASSISTANT_DISABLED
                    ),
                    old_value=old_master_value,
                    new_value=updated_settings.is_enabled,
                    scope="global",
                    description="The master AI Assistant setting changed.",
                    request=request,
                )
        messages.success(request, "AI Assistant settings were updated.")
        return redirect("management_ai_assistant_settings")
    return render(
        request,
        "dashboard/ai_assistant_settings.html",
        {
            "form": form,
            "assistant_settings": assistant_settings,
            "audit_events": AICapabilityAuditLog.objects.select_related(
                "acting_administrator", "capability"
            )[:30],
        },
    )


def management_audit_log(request):
    denied = require_staff(request)
    if denied:
        return denied
    audit_events = ContactAuditLog.objects.select_related(
        "acting_user", "item_report", "contact_request", "conversation"
    )
    return render(request, "dashboard/audit_log.html", {"audit_events": audit_events})


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)

# Create your views here.
