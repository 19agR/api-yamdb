from datetime import datetime, timedelta
from http import HTTPStatus
from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client
from django.utils import timezone
import pytest
from pytest_django.fixtures import SettingsWrapper
from rest_framework.test import APIClient

from reviews.models import Category, Comment, Genre, Review, Title
from tests.constants import (
    PROFILE_URL, SIGNUP_URL, TITLES_URL, TOKEN_URL, USERS_URL,
)
from users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog() -> tuple[Title, Title]:
    category = Category.objects.create(name='Movies', slug='movies')
    genre = Genre.objects.create(name='Drama', slug='drama')
    title = Title.objects.create(name='Arrival', year=2016, category=category)
    title.genre.add(genre)
    other_title = Title.objects.create(
        name='Contact', year=1997, category=category,
    )
    other_title.genre.add(genre)
    return title, other_title


def test_signup_email_code_produces_working_jwt(
    django_user_model: type[User],
) -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')
    payload = {'username': 'new.reader+1', 'email': 'reader@example.com'}
    response = client.post(SIGNUP_URL, {
        **payload, 'role': 'admin', 'is_staff': True, 'is_superuser': True,
    })
    assert response.status_code == HTTPStatus.OK
    assert response.json() == payload
    user = django_user_model.objects.get(username=payload['username'])
    assert user.role == 'user'
    assert not user.is_staff and not user.is_superuser
    assert not user.has_usable_password()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [payload['email']]
    code = mail.outbox[0].body.rsplit(' ', 1)[-1]
    response = client.post(TOKEN_URL, {
        'username': user.username, 'confirmation_code': code,
    })
    assert response.status_code == HTTPStatus.OK
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.json()["token"]}')
    response = client.get(PROFILE_URL)
    assert response.status_code == HTTPStatus.OK
    assert response.json()['username'] == user.username


def test_resend_does_not_change_existing_user(
    client: Client, admin: User,
) -> None:
    payload = {'username': admin.username, 'email': admin.email}
    for _ in range(2):
        assert client.post(SIGNUP_URL, payload).status_code == HTTPStatus.OK
    assert len(mail.outbox) == 2
    admin.refresh_from_db()
    assert admin.role == 'admin'
    assert admin.check_password('1234567')


def test_expired_code_is_rejected(
    client: Client, user: User, settings: SettingsWrapper,
) -> None:
    old_date = datetime.now() - timedelta(
        seconds=settings.PASSWORD_RESET_TIMEOUT + 10,
    )
    with patch.object(default_token_generator, '_now', return_value=old_date):
        code = default_token_generator.make_token(user)
    response = client.post(TOKEN_URL, {
        'username': user.username, 'confirmation_code': code,
    })
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'confirmation_code' in response.json()


def test_code_cannot_be_used_for_another_user(
    client: Client, user: User, admin: User,
) -> None:
    code = default_token_generator.make_token(user)
    response = client.post(TOKEN_URL, {
        'username': admin.username, 'confirmation_code': code,
    })
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_inactive_user_cannot_obtain_or_use_jwt(
    client: Client, user: User, user_client: APIClient,
) -> None:
    code = default_token_generator.make_token(user)
    user.is_active = False
    user.save()
    assert client.post(TOKEN_URL, {
        'username': user.username, 'confirmation_code': code,
    }).status_code == HTTPStatus.BAD_REQUEST
    assert user_client.get(PROFILE_URL).status_code == HTTPStatus.UNAUTHORIZED


def test_username_with_dot_is_addressable(
    admin_client: APIClient, django_user_model: type[User],
) -> None:
    user = django_user_model.objects.create_user(
        username='first.last+name@example', email='valid@example.com',
    )
    response = admin_client.get(f'{USERS_URL}{user.username}/')
    assert response.status_code == HTTPStatus.OK
    assert response.json()['username'] == user.username


def test_profile_cannot_elevate_any_privilege(
    user_client: APIClient, user: User,
) -> None:
    response = user_client.patch(PROFILE_URL, {
        'role': 'admin', 'is_staff': True, 'is_superuser': True,
        'bio': 'Updated bio',
    }, format='json')
    assert response.status_code == HTTPStatus.OK
    user.refresh_from_db()
    assert user.bio == 'Updated bio'
    assert user.role == 'user'
    assert not user.is_staff and not user.is_superuser


@pytest.mark.parametrize('method', ('get', 'post', 'patch', 'delete'))
def test_nested_routes_do_not_expose_another_title(
    method: str, catalog: tuple[Title, Title], user: User,
    user_client: APIClient,
) -> None:
    title, other_title = catalog
    review = Review.objects.create(
        title=title, author=user, text='Review', score=8,
    )
    comment = Comment.objects.create(
        review=review, author=user, text='Comment',
    )
    wrong_review_url = (
        f'{TITLES_URL}{other_title.pk}/reviews/{review.pk}/'
    )
    suffix = '' if method == 'post' else f'{comment.pk}/'
    wrong_comment_url = f'{wrong_review_url}comments/{suffix}'
    response = getattr(user_client, method)(wrong_comment_url)
    assert response.status_code == HTTPStatus.NOT_FOUND
    if method != 'post':
        assert getattr(user_client, method)(
            wrong_review_url,
        ).status_code == HTTPStatus.NOT_FOUND
    assert Comment.objects.filter(pk=comment.pk).exists()
    assert Review.objects.filter(pk=review.pk).exists()


@pytest.mark.parametrize('method', ('get', 'post'))
def test_missing_nested_parent_returns_404(
    method: str, user_client: APIClient,
) -> None:
    for url in (
        '/api/v1/titles/999/reviews/',
        '/api/v1/titles/999/reviews/999/comments/',
    ):
        response = getattr(user_client, method)(url)
        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize('field', ('category', 'genre'))
def test_deleting_classification_preserves_title(
    field: str, catalog: tuple[Title, Title], admin_client: APIClient,
) -> None:
    title, _ = catalog
    related = title.category if field == 'category' else title.genre.first()
    endpoint = 'categories' if field == 'category' else 'genres'
    assert admin_client.delete(
        f'/api/v1/{endpoint}/{related.slug}/',
    ).status_code == HTTPStatus.NO_CONTENT
    response = admin_client.get(f'{TITLES_URL}{title.pk}/')
    assert response.status_code == HTTPStatus.OK
    assert response.json()[field] == (None if field == 'category' else [])


@pytest.mark.parametrize('target', ('user', 'title', 'review'))
def test_cascades_remove_dependent_publications(
    target: str, catalog: tuple[Title, Title], user: User, moderator: User,
    admin_client: APIClient,
) -> None:
    title, other_title = catalog
    review = Review.objects.create(
        title=title, author=user, text='Review', score=8,
    )
    comment = Comment.objects.create(
        review=review, author=moderator, text='Comment',
    )
    unrelated = Review.objects.create(
        title=other_title, author=moderator, text='Other review', score=5,
    )
    urls = {
        'user': f'{USERS_URL}{user.username}/',
        'title': f'{TITLES_URL}{title.pk}/',
        'review': f'{TITLES_URL}{title.pk}/reviews/{review.pk}/',
    }
    response = admin_client.delete(urls[target])
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert not Review.objects.filter(pk=review.pk).exists()
    assert not Comment.objects.filter(pk=comment.pk).exists()
    assert Review.objects.filter(pk=unrelated.pk).exists()


@pytest.mark.parametrize('year', ('tomorrow', None, 99999))
def test_invalid_year_rejected_on_create_and_patch(
    year: str | int | None, catalog: tuple[Title, Title],
    admin_client: APIClient,
) -> None:
    title, _ = catalog
    payload = {
        'name': 'Invalid year', 'year': year,
        'category': title.category.slug, 'genre': ['drama'],
    }
    assert admin_client.post(
        TITLES_URL, payload, format='json',
    ).status_code == HTTPStatus.BAD_REQUEST
    assert admin_client.patch(
        f'{TITLES_URL}{title.pk}/', {'year': year}, format='json',
    ).status_code == HTTPStatus.BAD_REQUEST
    title.refresh_from_db()
    assert title.year == 2016


def test_current_year_allowed_next_year_rejected(
    catalog: tuple[Title, Title], admin_client: APIClient,
) -> None:
    title, _ = catalog
    url = f'{TITLES_URL}{title.pk}/'
    year = timezone.now().year
    assert admin_client.patch(url, {'year': year}).status_code == HTTPStatus.OK
    response = admin_client.patch(url, {'year': year + 1})
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_rating_tracks_review_updates_and_deletion(
    catalog: tuple[Title, Title], user: User, moderator: User,
    user_client: APIClient, moderator_client: APIClient,
    admin_client: APIClient,
) -> None:
    title, _ = catalog
    url = f'{TITLES_URL}{title.pk}/'
    reviews_url = f'{url}reviews/'
    assert user_client.get(url).json()['rating'] is None
    first = user_client.post(reviews_url, {'text': 'First', 'score': 6}).json()
    second = moderator_client.post(
        reviews_url, {'text': 'Second', 'score': 9},
    ).json()
    response = admin_client.patch(url, {'name': 'Updated title'})
    assert response.json()['rating'] == 7
    user_client.patch(f'{reviews_url}{first["id"]}/', {'score': 1})
    assert user_client.get(url).json()['rating'] == 5
    user_client.delete(f'{reviews_url}{first["id"]}/')
    assert user_client.get(url).json()['rating'] == 9
    moderator_client.delete(f'{reviews_url}{second["id"]}/')
    assert user_client.get(url).json()['rating'] is None


def test_authorship_and_publication_date_cannot_be_forged(
    catalog: tuple[Title, Title], user: User, moderator: User,
    user_client: APIClient,
) -> None:
    title, _ = catalog
    url = f'{TITLES_URL}{title.pk}/reviews/'
    response = user_client.post(url, {
        'text': 'Review', 'score': 8, 'author': moderator.username,
        'pub_date': '2000-01-01T00:00:00Z',
    })
    assert response.status_code == HTTPStatus.CREATED
    review = Review.objects.get(pk=response.json()['id'])
    assert review.author == user
    assert review.pub_date.year == timezone.now().year
    response = user_client.post(f'{url}{review.pk}/comments/', {
        'text': 'Comment', 'author': moderator.username,
        'pub_date': '2000-01-01T00:00:00Z',
    })
    assert response.status_code == HTTPStatus.CREATED
    comment = Comment.objects.get(pk=response.json()['id'])
    assert comment.author == user
    assert comment.pub_date.year == timezone.now().year


def test_staff_without_admin_role_has_no_api_admin_rights(
    user: User, user_client: APIClient,
) -> None:
    user.is_staff = True
    user.save()
    assert user_client.post('/api/v1/categories/', {
        'name': 'Unauthorized', 'slug': 'unauthorized',
    }).status_code == HTTPStatus.FORBIDDEN
    assert user_client.get(USERS_URL).status_code == HTTPStatus.FORBIDDEN


def test_superuser_role_user_can_manage_content(
    user_superuser_client: APIClient, catalog: tuple[Title, Title],
) -> None:
    title, _ = catalog
    assert user_superuser_client.patch(
        f'{TITLES_URL}{title.pk}/', {'name': 'Changed'},
    ).status_code == HTTPStatus.OK
    assert user_superuser_client.post('/api/v1/genres/', {
        'name': 'Comedy', 'slug': 'comedy',
    }).status_code == HTTPStatus.CREATED


def test_pagination_has_disjoint_pages(client: Client) -> None:
    Category.objects.bulk_create([
        Category(name=f'Category {index}', slug=f'category-{index}')
        for index in range(15)
    ])
    first = client.get('/api/v1/categories/').json()
    second = client.get('/api/v1/categories/?page=2').json()
    assert first['count'] == second['count'] == 15
    assert len(first['results']) == 10
    assert len(second['results']) == 5
    assert first['next'] and first['previous'] is None
    assert second['next'] is None and second['previous']
    first_slugs = {item['slug'] for item in first['results']}
    second_slugs = {item['slug'] for item in second['results']}
    assert first_slugs.isdisjoint(second_slugs)
