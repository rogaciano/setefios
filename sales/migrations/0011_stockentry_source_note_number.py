import re

from django.db import migrations, models


def populate_source_note_numbers(apps, schema_editor):
    StockEntry = apps.get_model("sales", "StockEntry")
    quoted_pattern = re.compile(r"\bNOTA\b\s*:\s*'([^']+)'", re.IGNORECASE)
    plain_pattern = re.compile(r"\bNOTA\b\s*[:#-]?\s*([A-Z0-9./-]+)", re.IGNORECASE)

    for entry in StockEntry.objects.filter(source_note_number="").iterator():
        notes = (entry.notes or "").strip()
        if not notes:
            continue

        note_number = ""
        quoted_match = quoted_pattern.search(notes.upper())
        if quoted_match:
            note_number = re.sub(r"\s+", "", quoted_match.group(1).strip().upper())
        else:
            plain_match = plain_pattern.search(notes.upper())
            if plain_match:
                candidate = re.sub(r"\s+", "", plain_match.group(1).strip().upper())
                if any(char.isdigit() for char in candidate):
                    note_number = candidate

        if note_number:
            entry.source_note_number = note_number
            entry.save(update_fields=["source_note_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_alter_stockmovement_movement_type_stockadjustment_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockentry",
            name="source_note_number",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40, verbose_name="nota de origem"),
        ),
        migrations.RunPython(populate_source_note_numbers, migrations.RunPython.noop),
    ]
