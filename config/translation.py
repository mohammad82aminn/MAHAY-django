"""Who may edit the site's English texts in Rosetta (development only, see ROSETTA_ENABLED in settings)."""


def can_translate(user):
    # Rosetta's own default also lets in anyone in a group named "translators"; here it is the
    # superuser alone, since what is typed there ends up on every page of the site.
    return user.is_authenticated and user.is_active and user.is_superuser
