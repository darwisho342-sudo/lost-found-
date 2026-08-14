"""Language-aware URL helpers."""

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def language_url(request, language_code):
    """Replace the active language prefix and retain the path and query string."""
    supported = {code for code, _name in settings.LANGUAGES}
    code = language_code if language_code in supported else settings.LANGUAGE_CODE
    parts = request.path.lstrip("/").split("/", 1)
    remainder = parts[1] if parts and parts[0] in supported and len(parts) > 1 else ""
    translated_path = f"/{code}/{remainder}"
    query = request.GET.urlencode()
    return f"{translated_path}?{query}" if query else translated_path
