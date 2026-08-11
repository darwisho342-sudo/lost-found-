def notification_center(request):
    if not request.user.is_authenticated:
        return {}
    notifications = request.user.notifications.all()
    return {
        "notification_preview": notifications[:6],
        "notification_unread_count": notifications.filter(is_read=False).count(),
    }
