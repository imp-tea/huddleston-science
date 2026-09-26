from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .discovery import calendar_progress, coverage_rows
from .models import Category, Subcategory, Topic, TopicCompletion, TopicRedirect
from .study import reading_snapshot


def library_url(category='', subcategory=''):
    params = {key: value for key, value in [('category', category), ('subcategory', subcategory)] if value}
    return reverse('scholars:library') + ('?' + urlencode(params) if params else '')


@login_required
@require_GET
def progress(request):
    return render(request, 'scholars/study/progress.html', {
        'coverage': coverage_rows(request.user), 'weekly': calendar_progress(request.user)})


@login_required
@require_GET
def library(request):
    category = request.GET.get('category', '')
    subcategory = request.GET.get('subcategory', '')
    query = request.GET.get('q', '')[:100].strip()
    cat = get_object_or_404(Category, pk=category, active=True) if category else None
    sub = Subcategory.objects.filter(pk=subcategory, active=True, category__active=True)
    if cat:
        sub = sub.filter(category=cat)
    sub = sub.first() if subcategory else None
    if sub and not cat:
        return redirect(library_url(sub.category_id, sub.pk))
    subcategory = sub.pk if sub else ''
    crumbs = [{'label': 'Explore', 'url': library_url()}]
    if cat:
        crumbs.append({'label': cat.pk, 'url': library_url(cat.pk)})
    if sub:
        crumbs.append({'label': sub.payload.get('label', sub.pk), 'url': library_url(cat.pk, sub.pk)})
    context = {'category': category, 'subcategory': subcategory, 'query': query, 'crumbs': crumbs,
               'heading': sub.payload.get('label', sub.pk) if sub else cat.pk if cat else 'Explore'}
    if sub or query:
        topics = Topic.objects.filter(active=True, category__active=True)
        if cat:
            topics = topics.filter(category=cat)
        if sub:
            topics = topics.filter(subcategories=sub)
        if query:
            topics = topics.filter(Q(title__icontains=query) | Q(payload__description__icontains=query) | Q(payload__aliases__icontains=query))
        page = Paginator(topics.only('id', 'title', 'category_id').order_by('title', 'pk'), 40).get_page(request.GET.get('page'))
        params = {k: v for k, v in [('category', category), ('subcategory', subcategory), ('q', query)] if v}
        context.update(topics=page, query_params=urlencode(params), topic_context=urlencode(
            {'category': category, 'subcategory': subcategory}) if sub else '')
    elif cat:
        context['subcategories'] = Subcategory.objects.filter(active=True, category=cat).annotate(
            total=Count('topic', filter=Q(topic__active=True, topic__category__active=True), distinct=True)).order_by('payload__label', 'pk')
    else:
        # Keep the topic and subcategory counts separate to avoid their Cartesian join.
        categories = list(Category.objects.filter(active=True).annotate(
            total=Count('topic', filter=Q(topic__active=True), distinct=True)).order_by('pk'))
        counts = dict(Subcategory.objects.filter(active=True, category__active=True).order_by()
                      .values('category_id').annotate(total=Count('pk')).values_list('category_id', 'total'))
        for category_row in categories:
            category_row.subjects = counts.get(category_row.pk, 0)
        context['categories'] = categories
    return render(request, 'scholars/study/explore.html', context)


@login_required
@require_GET
def topic(request, pk):
    old = TopicRedirect.objects.filter(pk=pk, active=True, topic__active=True, topic__category__active=True).first()
    if old:
        params = {key: request.GET[key] for key in ('category', 'subcategory') if request.GET.get(key)}
        url = reverse('scholars:topic', args=[old.topic_id])
        return redirect(url + ('?' + urlencode(params) if params else ''), permanent=True)
    entry = get_object_or_404(Topic, pk=pk, active=True, category__active=True)
    sub_id = request.GET.get('subcategory', '')
    sub = get_object_or_404(entry.subcategories, pk=sub_id, active=True, category_id=entry.category_id) if sub_id else None
    crumbs = [{'label': 'Explore', 'url': library_url()},
              {'label': entry.category_id, 'url': library_url(entry.category_id)}]
    if sub:
        crumbs.append({'label': sub.payload.get('label', sub.pk), 'url': library_url(entry.category_id, sub.pk)})
    crumbs.append({'label': entry.title})
    return render(request, 'scholars/study/explore_topic.html', {'card': reading_snapshot(entry), 'crumbs': crumbs,
        'completion': TopicCompletion.objects.filter(user=request.user, topic=entry).first()})
