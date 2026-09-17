import csv
from io import StringIO
from pathlib import Path
from shutil import copyfile

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from reviews.models import Category, Comment, Genre, GenreTitle, Review, Title
from users.models import User

pytestmark = pytest.mark.django_db
MODELS = (User, Category, Genre, Title, GenreTitle, Review, Comment)
EXPECTED_COUNTS = (5, 3, 15, 32, 42, 72, 3)


@pytest.fixture
def csv_directory(tmp_path: Path) -> Path:
    for source in (settings.BASE_DIR / 'static' / 'data').glob('*.csv'):
        copyfile(source, tmp_path / source.name)
    return tmp_path


def model_counts() -> tuple[int, ...]:
    return tuple(model.objects.count() for model in MODELS)


def test_import_preserves_relations_dates_and_is_repeatable() -> None:
    output = StringIO()
    call_command('import_csv', strict=True, stdout=output)
    assert model_counts() == EXPECTED_COUNTS
    with (settings.BASE_DIR / 'static/data/review.csv').open(
        encoding='utf-8', newline='',
    ) as source:
        row = next(csv.DictReader(source))
    review = Review.objects.get(pk=row['id'])
    assert review.text == row['text']
    assert review.author_id == int(row['author'])
    assert review.title_id == int(row['title_id'])
    assert review.pub_date.isoformat() == '2019-09-24T21:08:21.567000+00:00'
    assert all(not user.has_usable_password() for user in User.objects.all())
    user = User.objects.get(pk=100)
    user.bio = 'Local edit must survive another import'
    user.save()
    output = StringIO()
    call_command('import_csv', strict=True, stdout=output)
    assert model_counts() == EXPECTED_COUNTS
    assert 'добавлено 0' in output.getvalue()
    user.refresh_from_db()
    assert user.bio == 'Local edit must survive another import'


def test_invalid_rows_are_reported_and_valid_rows_continue(
    csv_directory: Path,
) -> None:
    with (csv_directory / 'comments.csv').open(
        'a', encoding='utf-8',
    ) as target:
        target.write('\n4,999999,Missing review,100,2020-01-01T00:00:00Z\n')
        target.write('5,6,Valid comment,100,2020-01-01T00:00:00Z\n')
    errors = StringIO()
    call_command('import_csv', path=csv_directory, stdout=StringIO(),
                 stderr=errors)
    assert Comment.objects.count() == 4
    assert Comment.objects.filter(pk=5).exists()
    assert not Comment.objects.filter(pk=4).exists()
    assert 'comments.csv' in errors.getvalue()


def test_strict_import_rolls_back_every_file(csv_directory: Path) -> None:
    with (csv_directory / 'comments.csv').open(
        'a', encoding='utf-8',
    ) as target:
        target.write('\n4,999999,Missing review,100,2020-01-01T00:00:00Z\n')
    with pytest.raises(CommandError, match='comments.csv'):
        call_command('import_csv', path=csv_directory, strict=True,
                     stdout=StringIO())
    assert model_counts() == (0,) * len(MODELS)


def test_unique_constraints_skip_duplicate_review(csv_directory: Path) -> None:
    with (csv_directory / 'review.csv').open('a', encoding='utf-8') as target:
        target.write('\n999,1,Duplicate review,100,7,2020-01-01T00:00:00Z\n')
    errors = StringIO()
    call_command('import_csv', path=csv_directory, stdout=StringIO(),
                 stderr=errors)
    assert model_counts() == EXPECTED_COUNTS
    assert 'review.csv' in errors.getvalue()


def test_missing_files_fail_before_import(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match='users.csv'):
        call_command('import_csv', path=tmp_path, stdout=StringIO())
    assert model_counts() == (0,) * len(MODELS)


def test_bad_csv_header_rolls_back_import(csv_directory: Path) -> None:
    (csv_directory / 'comments.csv').write_text(
        'text\nComment\n', encoding='utf-8',
    )
    with pytest.raises(CommandError, match='comments.csv'):
        call_command('import_csv', path=csv_directory, stdout=StringIO())
    assert model_counts() == (0,) * len(MODELS)


def test_utf8_bom_is_supported(csv_directory: Path) -> None:
    source = Path(csv_directory / 'category.csv')
    contents = source.read_text(encoding='utf-8')
    source.write_text(contents, encoding='utf-8-sig')
    call_command('import_csv', path=csv_directory, strict=True,
                 stdout=StringIO())
    assert model_counts() == EXPECTED_COUNTS
