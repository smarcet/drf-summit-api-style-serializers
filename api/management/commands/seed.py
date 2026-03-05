from django.core.management.base import BaseCommand
from api.models import Owner, MediaUpload, Item, Tag

class Command(BaseCommand):
    def handle(self, *args, **options):
        Item.objects.all().delete()
        Tag.objects.all().delete()
        MediaUpload.objects.all().delete()
        Owner.objects.all().delete()

        o1 = Owner.objects.create(name="Alice")
        o2 = Owner.objects.create(name="Bob")
        m1 = MediaUpload.objects.create(url="https://example.com/a.png", owner=o1)
        m2 = MediaUpload.objects.create(url="https://example.com/b.png", owner=o2)

        t1 = Tag.objects.create(name="alpha")
        t2 = Tag.objects.create(name="beta")
        t3 = Tag.objects.create(name="gamma")

        i1 = Item.objects.create(name="Widget A", quantity=2, media_upload_id=m1.id)
        i2 = Item.objects.create(name="Widget B", quantity=5, media_upload_id=m2.id)
        i3 = Item.objects.create(name="Widget C", quantity=1, media_upload_id=None)

        i1.tags.set([t1, t2])
        i2.tags.set([t2, t3])
        i3.tags.set([])
        self.stdout.write(self.style.SUCCESS("Seeded sample data."))
