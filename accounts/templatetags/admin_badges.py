"""The red counts beside the sections of the admin panel."""
from django import template
from django.apps import apps

from ..pending import count_for

register = template.Library()


@register.simple_tag(takes_context=True)
def pending_count(context, app_label, object_name):
    """
    How many rows of this model wait for the visitor; 0 renders nothing in the template.

    The model is named rather than handed over as a class on purpose: the template engine calls
    anything callable it resolves, and calling a model class builds an empty unsaved instance.
    """
    request = context.get("request")
    if request is None:
        return 0
    try:
        model = apps.get_model(app_label, object_name)
    except LookupError:
        return 0
    return count_for(model, request)
