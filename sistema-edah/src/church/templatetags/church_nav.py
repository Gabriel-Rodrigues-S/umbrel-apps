from django import template

register = template.Library()


@register.simple_tag
def nav_active(request, name):
    if getattr(request, "resolver_match", None) and request.resolver_match.url_name == name:
        return "active"
    return ""


@register.simple_tag
def nav_active_prefix(request, prefix):
    path = getattr(request, "path", "") or ""
    if path.startswith(prefix):
        return "active"
    return ""


@register.filter
def nivel_in(user, csv):
    if not user.is_authenticated:
        return False
    nivel = getattr(user, "nivel_acesso", "") or ""
    return nivel in [x.strip() for x in csv.split(",") if x.strip()]
