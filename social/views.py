from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .feed import get_feed_page
from .forms import PostCreateForm, ReshareForm
from .models import Follow, Post
from .services import create_post


@login_required
def feed(request):
    try:
        page = get_feed_page(viewer=request.user, cursor=request.GET.get('cursor'))
    except ValidationError as error:
        return HttpResponseBadRequest('; '.join(error.messages))
    return render(request, 'social/feed.html', {'page': page})


def profile(request, username):
    profile_user = get_object_or_404(get_user_model(), username=username)
    posts = (
        Post.objects.filter(author=profile_user, is_deleted=False)
        .select_related('author', 'reshared_post', 'reshared_post__author')
        .prefetch_related('images')
        .order_by('-created_at', '-pk')[:50]
    )
    is_following = (
        request.user.is_authenticated
        and Follow.objects.filter(follower=request.user, followed=profile_user).exists()
    )
    return render(
        request,
        'social/profile.html',
        {
            'profile_user': profile_user,
            'posts': posts,
            'is_following': is_following,
        },
    )


@login_required
def post_create(request):
    if request.method == 'POST':
        form = PostCreateForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                create_post(
                    author=request.user,
                    body=form.cleaned_data['body'],
                    images=form.cleaned_data['images'],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Your post is published.')
                return redirect('social:feed')
    else:
        form = PostCreateForm()
    return render(request, 'social/post_form.html', {'form': form})


@login_required
@require_POST
def follow_user(request, username):
    target = get_object_or_404(get_user_model(), username=username)
    if target.pk == request.user.pk:
        messages.error(request, 'You cannot follow yourself.')
    else:
        _, created = Follow.objects.get_or_create(follower=request.user, followed=target)
        messages.success(
            request,
            f'You are now following {target.username}.'
            if created
            else f'You already follow {target.username}.',
        )
    return redirect('social:profile', username=target.username)


@login_required
@require_POST
def unfollow_user(request, username):
    target = get_object_or_404(get_user_model(), username=username)
    Follow.objects.filter(follower=request.user, followed=target).delete()
    messages.success(request, f'You unfollowed {target.username}.')
    return redirect('social:profile', username=target.username)


@login_required
@require_POST
def reshare(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    original = post.reshared_post if post.reshared_post_id else post
    form = ReshareForm(request.POST)
    if post.is_deleted or original.is_deleted:
        messages.error(request, 'This post is no longer available to reshare.')
    elif form.is_valid():
        try:
            create_post(
                author=request.user,
                body=form.cleaned_data['body'],
                reshared_post=original,
            )
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        else:
            messages.success(request, 'Post reshared to your feed.')
    else:
        messages.error(request, 'Your reshare comment could not be used.')
    return redirect('social:feed')
