from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Read a dict by key inside a template: {{ progress|get_item:lesson.pk }}"""
    return (mapping or {}).get(key)