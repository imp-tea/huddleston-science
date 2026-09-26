import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .discovery import calendar_progress, coverage_rows
from .models import (Category, StudyActivity, StudySession, StudyState, Subcategory,
                     Topic, TopicCompletion, TopicRedirect)
from .study import save_interests
from .test_study import seed_study

UTC = dt_timezone.utc


class DiscoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = seed_study()
        cls.other = User.objects.create_user('discovery-other', 'Password-123!', must_change_password=False)

    def setUp(self):
        self.client.force_login(self.user)

    def passed(self, at=None, user=None):
        return StudySession.objects.create(user=user or self.user, request_key=uuid.uuid4(), subcategory_id='sub-00',
            category_label='Geography', subcategory_label='Subject 0', phase='passed', completed_at=at or timezone.now())

    def complete(self, topic='topic-0', session=None):
        return TopicCompletion.objects.create(user=self.user, topic_id=topic, session=session or self.passed())

    def test_coverage_identity_memberships_interests_and_retirements(self):
        session = self.passed()
        self.complete(session=session)
        StudyState.objects.create(user=self.user, topic_id='topic-1', studied_at=timezone.now(), last_opened_at=timezone.now())
        clone = Topic.objects.create(pk='same-subject', subject_id='subject-0', title='Another record',
            category_id='Literature', payload={})
        outside = Subcategory.objects.create(pk='outside', category_id='Literature', payload={'label': 'Outside interests'})
        clone.subcategories.add(outside)
        totals = coverage_rows(self.user)
        self.assertEqual((totals['done'], totals['total']), (1, 7))
        geography = next(c for c in totals['categories'] if c.pk == 'Geography')
        self.assertEqual((geography.done, geography.total), (1, 6))
        self.assertTrue(all(s.done == 1 for s in geography.subs))
        self.assertEqual(coverage_rows(self.other)['done'], 0)
        save_interests(self.user, ['Literature'])
        self.assertEqual(coverage_rows(self.user)['done'], 1)
        Topic.objects.filter(pk='topic-0').update(active=False)
        self.assertEqual((coverage_rows(self.user)['done'], coverage_rows(self.user)['total']), (0, 6))
        self.assertTrue(TopicCompletion.objects.filter(session=session).exists())
        self.assertEqual(StudySession.objects.get(pk=session.pk).phase, 'passed')
        Topic.objects.filter(pk='topic-0').update(active=True)
        self.assertEqual(coverage_rows(self.user)['done'], 1)
        Category.objects.filter(pk='Geography').update(active=False)
        self.assertEqual(coverage_rows(self.user)['total'], 1)

    def test_week_boundaries_chicago_and_goal_overflow(self):
        # UTC Monday before Chicago midnight remains in the previous week.
        self.passed(datetime(2026, 9, 28, 4, 59, tzinfo=UTC))
        at = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)
        for _ in range(7):
            self.passed(at)
        self.passed(at, self.other)
        self.assertEqual(calendar_progress(self.user, at - timedelta(seconds=1))['count'], 1)
        weekly = calendar_progress(self.user, at)
        self.assertEqual((weekly['count'], weekly['percent'], weekly['fill'], weekly['remaining']), (7, 140, 100, 0))
        self.assertEqual(weekly['week_start'].isoformat(), '2026-09-28')
        self.assertEqual(len(weekly['days']), 35)
        self.assertEqual(weekly['days'][0]['date'].weekday(), 0)
        self.assertEqual(weekly['days'][-1]['date'].weekday(), 6)
        self.assertEqual(sum(day['passed'] for day in weekly['days']), 8)
        self.assertEqual(sum(day['future'] for day in weekly['days']), 6)
        with timezone.override(ZoneInfo('Asia/Tokyo')):
            self.assertEqual(calendar_progress(self.user, at), weekly)

    def test_dst_transition_weeks(self):
        # Both repeated fall hours and the spring skipped hour belong to Sunday.
        for year, month, day, hours in [(2026, 11, 1, (6, 7)), (2026, 3, 8, (7, 8))]:
            for hour in hours:
                self.passed(datetime(year, month, day, hour, 30, tzinfo=UTC))
            report = calendar_progress(self.user, datetime(year, month, day, 23, tzinfo=UTC))
            self.assertEqual(report['count'], 2)
            self.assertEqual(report['days'][-1]['passed'], 2)

    def test_activity_does_not_count_as_pass_and_duplicates_do_not_inflate_goal(self):
        at = datetime(2026, 9, 25, 18, tzinfo=UTC)
        passed = self.passed(at)
        abandoned = StudySession.objects.create(user=self.user, request_key=uuid.uuid4(), subcategory_id='sub-00',
            phase='abandoned', abandoned_at=at)
        for kind in ['reading', 'quiz', 'passed', 'passed']:
            StudyActivity.objects.create(session=passed, kind=kind, created_at=at)
        StudyActivity.objects.create(session=abandoned, kind='reading', created_at=at - timedelta(days=1))
        StudyActivity.objects.create(session=passed, kind='quiz', created_at=at - timedelta(days=2))
        StudyActivity.objects.create(session=self.passed(at, self.other), kind='reading', created_at=at)
        weekly = calendar_progress(self.user, at)
        self.assertEqual(weekly['count'], 1)
        self.assertEqual(weekly['days'][30]['level'], 2)
        self.assertEqual(weekly['days'][31]['level'], 1)
        self.assertEqual(weekly['days'][32]['level'], 3)
        self.assertIn('1 reading actions, 1 quiz answers, 1 completed sessions', weekly['days'][32]['label'])

    def test_progress_private_accessible_and_bounded_queries(self):
        self.complete()
        response = self.client.get(reverse('scholars:progress'), {'user': self.other.pk})
        self.assertEqual(response.context['coverage']['done'], 1)
        self.assertContains(response, 'role="listitem"', count=35)
        self.assertContains(response, 'aria-label="Weekly session goal"')
        self.assertContains(response, 'Literature')
        with CaptureQueriesContext(connection) as queries:
            coverage_rows(self.user)
            calendar_progress(self.user)
        self.assertEqual(len(queries), 5)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('scholars:progress'), {'user': self.user.pk}).context['coverage']['done'], 0)
        self.client.logout()
        for name in ['progress', 'library', 'topic']:
            self.assertEqual(self.client.get(reverse('scholars:' + name, args=['topic-0'] if name == 'topic' else [])).status_code, 302)

    def test_explore_hierarchy_search_pagination_and_entry_breadcrumb(self):
        url = reverse('scholars:library')
        response = self.client.get(url)
        self.assertContains(response, 'Literature')  # Includes unselected interests.
        self.assertNotContains(response, 'Topic 0')
        self.assertEqual(next(c for c in response.context['categories'] if c.pk == 'Geography').total, 6)
        response = self.client.get(url, {'category': 'Geography'})
        self.assertContains(response, 'Subject 24')
        response = self.client.get(url, {'category': 'Geography', 'subcategory': 'sub-24'})
        self.assertEqual(response.context['topics'].paginator.count, 6)
        self.assertContains(response, 'subcategory=sub-24')
        response = self.client.get(reverse('scholars:topic', args=['topic-0']), {'subcategory': 'sub-24'})
        self.assertContains(response, 'Subject 24')
        self.assertNotContains(response, 'Subject 0')
        self.assertNotContains(response, 'Canonical')
        self.assertNotContains(response, 'Prompt 0')
        self.assertFalse(TopicCompletion.objects.exists())
        self.assertFalse(StudyActivity.objects.exists())
        self.assertFalse(StudyState.objects.exists())
        self.assertEqual(self.client.get(reverse('scholars:topic', args=['topic-1']), {'subcategory': 'small'}).status_code, 404)
        for i in range(45):
            Topic.objects.create(pk=f'search-{i}', title=f'Searchable {i:02}', subject_id=f'search-{i}', category_id='Literature', payload={})
        response = self.client.get(url, {'q': 'Searchable', 'page': 2})
        self.assertEqual(len(response.context['topics']), 5)
        self.assertContains(response, 'q=Searchable')
        response = self.client.get(url, {'q': 'Searchable', 'category': 'Geography'})
        self.assertEqual(response.context['topics'].paginator.count, 0)
        self.assertContains(response, 'No matching topics')
        Topic.objects.filter(pk='topic-0').update(payload={'aliases': ['Distinctive alternative name']})
        response = self.client.get(url, {'q': 'Distinctive alternative'})
        self.assertEqual([t.pk for t in response.context['topics']], ['topic-0'])
        self.assertEqual(self.client.get(url, {'category': 'missing'}).status_code, 404)

    def test_topic_redirects_completion_and_retirement(self):
        self.complete()
        TopicRedirect.objects.create(pk='old-id', topic_id='topic-0')
        response = self.client.get(reverse('scholars:topic', args=['old-id']), {'subcategory': 'small'}, follow=True)
        self.assertEqual(response.redirect_chain[0][1], 301)
        self.assertContains(response, 'Small subject')
        self.assertContains(response, 'View study session')
        Topic.objects.filter(pk='topic-0').update(active=False)
        self.assertEqual(self.client.get(reverse('scholars:topic', args=['topic-0'])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('scholars:library'), {'q': 'Topic 0'}), 'class="topic-arrow"')
        Subcategory.objects.filter(pk='small').update(active=False)
        self.assertNotContains(self.client.get(reverse('scholars:library'), {'category': 'Geography'}), 'Small subject')

    def test_history_keeps_all_sessions_and_empty_progress(self):
        for _ in range(22):
            self.passed()
        response = self.client.get(reverse('scholars:history'), {'study_page': 2})
        self.assertEqual(len(response.context['study_sessions']), 2)
        self.assertContains(response, 'Previous practice statistics')
        self.client.force_login(self.other)
        response = self.client.get(reverse('scholars:progress'))
        self.assertEqual(response.context['weekly']['count'], 0)
        self.assertEqual(response.context['coverage']['done'], 0)
        Category.objects.update(active=False)
        response = self.client.get(reverse('scholars:progress'))
        self.assertContains(response, 'No topics are available yet.')
