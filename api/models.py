from django.db import models

class Owner(models.Model):
    name = models.CharField(max_length=200)

class MediaUpload(models.Model):
    url = models.URLField()
    owner = models.ForeignKey(Owner, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploads")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

class Item(models.Model):
    name = models.CharField(max_length=200)
    quantity = models.IntegerField(default=1)
    media_upload_id = models.IntegerField(null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="items")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    @property
    def media_upload(self):
        if hasattr(self, "_prefetched_media_upload"):
            return getattr(self, "_prefetched_media_upload")
        if not self.media_upload_id:
            return None
        return MediaUpload.objects.filter(pk=self.media_upload_id).first()
