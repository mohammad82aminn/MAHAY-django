from django.db import migrations


def fill_durations(apps, schema_editor):
    """
    Lessons saved before durations were read from the video: an uploaded video is measured from
    its file (and the minutes someone typed are dropped); an Aparat lesson keeps its typed minutes.
    If a file can't be read (missing from disk, damaged), the typed minutes stay as they were.
    """
    from content.video import mp4_seconds

    Lesson = apps.get_model("content", "Lesson")
    for lesson in Lesson.objects.all().iterator():
        seconds = mp4_seconds(lesson.video_file) if lesson.video_file else None
        if seconds is not None:
            lesson.duration_seconds, lesson.duration_minutes = seconds, None
        else:
            lesson.duration_seconds = lesson.duration_minutes * 60 if lesson.duration_minutes else None
        lesson.save(update_fields=["duration_seconds", "duration_minutes"])


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0003_lesson_duration_seconds_and_more"),
    ]

    operations = [
        migrations.RunPython(fill_durations, migrations.RunPython.noop),
    ]
