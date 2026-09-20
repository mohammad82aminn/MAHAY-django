"""Template helper for showing who somebody is. Named so it is not mistaken for accounts.roles."""
from django import template

from ..roles import role_label

register = template.Library()


@register.simple_tag
def user_role(user):
    if not getattr(user, "is_authenticated", False):
        return ""
    return role_label(user)
