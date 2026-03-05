from django.contrib import admin
from .models import Item, MediaUpload, Tag, Owner
admin.site.register(Item)
admin.site.register(MediaUpload)
admin.site.register(Tag)
admin.site.register(Owner)
