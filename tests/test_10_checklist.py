from http import HTTPStatus
from io import StringIO
from pathlib import Path
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
import pytest
from rest_framework.test import APIClient

from api.serializers import ReviewSerializer, SignupSerializer
from reviews.admin import GenreTitleInline
from reviews.management.commands.import_csv import Command
from reviews.models import Category, Comment, Genre, Review, Title
from tests.constants import (
    PROFILE_URL, SIGNUP_URL, TITLES_URL, USERS_URL,
)
from users.models import User

pytestmark = pytest.mark.django_db


def test_unrelated_signup_integrity_error_is_not_a_client_error() -> None:
    serializer = SignupSerializer(data={
        'username': 'valid', 'email': 'valid@example.com',
    })
    serializer.is_valid(raise_exception=True)
    with patch('api.serializers.User.objects.get_or_create',
               side_effect=IntegrityError('unrelated storage error')):
        with pytest.raises(IntegrityError, match='unrelated storage error'):
            serializer.save()


def test_unrelated_review_integrity_error_is_not_a_duplicate(
    user_client: APIClient,
) -> None:
    title = Title.objects.create(name='Title', year=2000)
    with patch.object(ReviewSerializer, 'save',
                      side_effect=IntegrityError('unrelated storage error')):
        with pytest.raises(IntegrityError, match='unrelated storage error'):
            user_client.post(f'{TITLES_URL}{title.pk}/reviews/', {
                'text': 'Valid review', 'score': 5,
            })


def test_import_does_not_hide_programming_type_errors() -> None:
    command = Command(stderr=StringIO())
    with patch.object(command, 'save_row',
                      side_effect=TypeError('programming error')):
        with pytest.raises(TypeError, match='programming error'):
            command.import_row({}, Title, {}, 'titles.csv', 2, False)


@pytest.mark.parametrize(
    'failure', (SMTPException('down'), OSError('down'), 0),
)
def test_failed_confirmation_delivery_can_be_retried(
    failure: Exception | int, client: Client, django_user_model: type[User],
) -> None:
    payload = {'username': 'retry_user', 'email': 'retry@example.com'}
    # Patch the backend method, keeping the actual signup/service path intact.
    kwargs = {'side_effect': failure} if isinstance(
        failure, Exception,
    ) else {'return_value': failure}
    with patch('django.core.mail.backends.locmem.EmailBackend.send_messages',
               **kwargs):
        response = client.post(SIGNUP_URL, payload)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert django_user_model.objects.filter(username='retry_user').count() == 1
    assert client.post(SIGNUP_URL, payload).status_code == HTTPStatus.OK


def test_admin_creation_validates_normalized_email(
    admin_client: APIClient, user: User,
) -> None:
    response = admin_client.post(USERS_URL, {
        'username': 'another_user', 'email': user.email.upper().replace(
            'TESTUSER', 'testuser',
        ),
    })
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'email' in response.json()


def test_import_invalid_id_is_a_row_error() -> None:
    errors = StringIO()
    command = Command(stderr=errors)
    result = command.import_row(
        {'id': None}, Title, {}, 'titles.csv', 2, False,
    )
    assert result == 2
    assert 'id' in errors.getvalue()


@pytest.mark.parametrize('resource,queries', (
    ('titles', 3), ('reviews', 3), ('comments', 3),
))
def test_content_lists_have_bounded_query_count(
    resource: str, queries: int, user: User,
) -> None:
    category = Category.objects.create(name='Books', slug='books')
    genre = Genre.objects.create(name='Fiction', slug='fiction')
    titles = [Title.objects.create(
        name=f'Title {index}', year=2000, category=category,
    ) for index in range(10)]
    for title in titles:
        title.genre.add(genre)
    authors = [user] + [User.objects.create_user(
        username=f'reviewer{index}', email=f'reviewer{index}@example.com',
    ) for index in range(9)]
    reviews = [Review.objects.create(
        title=titles[0], author=author, text='Review', score=5,
    ) for author in authors]
    for index in range(10):
        Comment.objects.create(review=reviews[0], author=user, text=str(index))
    urls = {
        'titles': TITLES_URL,
        'reviews': f'{TITLES_URL}{titles[0].pk}/reviews/',
        'comments': (
            f'{TITLES_URL}{titles[0].pk}/reviews/{reviews[0].pk}/comments/'
        ),
    }
    with CaptureQueriesContext(connection) as captured:
        response = APIClient().get(urls[resource])
    assert response.status_code == HTTPStatus.OK
    assert len(captured) == queries


@pytest.mark.parametrize('path', (
    '/admin/reviews/title/?q=Arrival',
    '/admin/reviews/title/?category__id__exact=1',
    '/admin/reviews/review/?score__exact=5',
    '/admin/reviews/comment/?q=Comment',
    '/admin/users/user/?role__exact=user',
))
def test_admin_lists_search_and_filters_render(
    path: str, client: Client, user_superuser: User,
) -> None:
    category = Category.objects.create(pk=1, name='Films', slug='films')
    title = Title.objects.create(name='Arrival', year=2016, category=category)
    other_title = Title.objects.create(name='Other', year=2000)
    publications = ((title, 5, 'Comment'), (other_title, 1, 'Other'))
    for item, score, text in publications:
        review = Review.objects.create(
            title=item, author=user_superuser, text=text, score=score,
        )
        Comment.objects.create(review=review, author=user_superuser, text=text)
    User.objects.create_user(
        username='admin_role', email='admin_role@example.com', role='admin',
    )
    client.force_login(user_superuser)
    response = client.get(path)
    assert response.status_code == HTTPStatus.OK
    assert response.context['cl'] is not None
    assert response.context['cl'].result_count == 1


def test_full_multiline_text_survives_import_and_api(client: Client) -> None:
    call_command('import_csv', strict=True, stdout=StringIO())
    title = Title.objects.get(pk=1)
    review = Review.objects.get(pk=1)
    response = client.get(f'{TITLES_URL}{title.pk}/reviews/{review.pk}/')
    assert response.json()['text'] == review.text
    assert '\n' in review.text
    assert title.name == 'Побег из Шоушенка'


def test_inline_string_labels_have_no_n_plus_one_queries(
    user_superuser: User,
) -> None:
    title = Title.objects.create(name='Title', year=2000)
    for index in range(10):
        genre = Genre.objects.create(name=f'Genre {index}', slug=f'g-{index}')
        title.genre.add(genre)
    inline = GenreTitleInline(Title, admin.site)
    request = RequestFactory().get('/admin/')
    request.user = user_superuser
    with CaptureQueriesContext(connection) as captured:
        labels = [str(link) for link in inline.get_queryset(request)]
    assert len(labels) == 10
    assert len(captured) == 1


@pytest.mark.parametrize('endpoint', ('signup', 'admin', 'profile'))
def test_email_domain_normalization_on_all_writes(
    endpoint: str, client: Client, admin_client: APIClient,
    user_client: APIClient, user: User,
) -> None:
    payload = {'email': 'normalized@EXAMPLE.COM'}
    if endpoint == 'signup':
        response = client.post(SIGNUP_URL, {
            **payload, 'username': 'normalized',
        })
    elif endpoint == 'admin':
        response = admin_client.patch(f'{USERS_URL}{user.username}/', payload)
    else:
        response = user_client.patch(PROFILE_URL, payload)
    assert response.status_code == HTTPStatus.OK
    assert response.json()['email'] == 'normalized@example.com'


def test_email_logs_omit_recipient_and_code(
    client: Client, caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level('INFO', logger='api.services'):
        response = client.post(SIGNUP_URL, {
            'username': 'safe_logs', 'email': 'private@example.com',
        })
    assert response.status_code == HTTPStatus.OK
    assert 'delivery started' in caplog.text
    assert 'delivery completed' in caplog.text
    assert 'private@example.com' not in caplog.text
    assert 'Ваш код подтверждения' not in caplog.text


def test_missing_csv_column_cannot_silently_use_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / 'users.csv'
    source.write_text('id,username\n1,name\n', encoding='utf-8')
    command = Command()
    with pytest.raises(CommandError, match='email'):
        command.import_file(source, User, {'email': 'email'}, False)


def test_import_distinguishes_empty_optional_field_and_zero() -> None:
    command = Command(stderr=StringIO())
    result = command.import_row(
        {'id': '1', 'name': 'Zero year', 'year': '0', 'description': ''},
        Title, {'name': 'name', 'year': 'year', 'description': 'description'},
        'titles.csv', 2, False,
    )
    # Category is mandatory when validating a supplied title CSV row.
    assert result == 2
    category = Category.objects.create(name='Books', slug='books')
    result = command.import_row(
        {'id': '1', 'name': 'Zero year', 'year': '0', 'description': '',
         'category': str(category.pk)},
        Title, {'name': 'name', 'year': 'year', 'description': 'description',
                'category': 'category_id'},
        'titles.csv', 2, False,
    )
    assert result == 0
    title = Title.objects.get(pk=1)
    assert title.year == 0 and title.description == ''


def test_title_after_first_page_is_still_addressable(client: Client) -> None:
    titles = Title.objects.bulk_create([
        Title(name=f'Title {index}', year=2000) for index in range(15)
    ])
    response = client.get(f'{TITLES_URL}{titles[-1].pk}/')
    assert response.status_code == HTTPStatus.OK
    assert response.json()['id'] == titles[-1].pk


@pytest.mark.parametrize('endpoint', ('signup', 'admin', 'profile'))
def test_username_normalization_cannot_bypass_unique_validation(
    endpoint: str, client: Client, admin_client: APIClient,
    user_client: APIClient, user: User,
) -> None:
    User.objects.create_user(username='taken', email='taken@example.com')
    payload = {'username': 'ｔａｋｅｎ'}
    if endpoint == 'signup':
        response = client.post(SIGNUP_URL, {
            **payload, 'email': 'new@example.com',
        })
    elif endpoint == 'admin':
        response = admin_client.post(USERS_URL, {
            **payload, 'email': 'new@example.com',
        })
    else:
        response = user_client.patch(PROFILE_URL, payload)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'username' in response.json()
