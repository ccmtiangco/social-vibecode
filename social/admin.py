from django.contrib import admin

from .models import Follow, Post, PostImage


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'body', 'reshared_post', 'is_deleted', 'created_at')
    list_filter = ('is_deleted', 'created_at')
    search_fields = ('body', 'author__username')
    raw_id_fields = ('author', 'reshared_post')
    readonly_fields = ('created_at', 'deleted_at')
    actions = None
    list_select_related = ('author', 'reshared_post')


@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'post', 'position', 'image', 'alt_text', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('alt_text', 'post__body', 'post__author__username')
    raw_id_fields = ('post',)
    readonly_fields = ('created_at',)
    list_select_related = ('post', 'post__author')


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'followed', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('follower__username', 'followed__username')
    raw_id_fields = ('follower', 'followed')
    readonly_fields = ('created_at',)
    list_select_related = ('follower', 'followed')
