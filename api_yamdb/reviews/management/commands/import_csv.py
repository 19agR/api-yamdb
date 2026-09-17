from __future__ import annotations

import csv
from collections import Counter
from enum import IntEnum
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import (
    BaseCommand, CommandError, CommandParser,
)
from django.db import IntegrityError, transaction
from django.db.models import Model

from reviews.models import Category, Comment, Genre, GenreTitle, Review, Title

User = get_user_model()
CSVRow = dict[str | None, str | list[str] | None]


class RowResult(IntEnum):
    """Обозначить исход обработки одной строки CSV."""

    CREATED = 0
    EXISTING = 1
    INVALID = 2


class Command(BaseCommand):
    """Загрузить связанные CSV с проверкой данных и атомарным откатом."""

    help = 'Загрузить CSV YaMDb с сохранением идентификаторов и связей.'

    IMPORTS = (
        ('users.csv', User, {
            'username': 'username', 'email': 'email', 'role': 'role',
            'bio': 'bio', 'first_name': 'first_name', 'last_name': 'last_name',
        }),
        ('category.csv', Category, {'name': 'name', 'slug': 'slug'}),
        ('genre.csv', Genre, {'name': 'name', 'slug': 'slug'}),
        ('titles.csv', Title, {
            'name': 'name', 'year': 'year', 'category': 'category_id',
        }),
        ('genre_title.csv', GenreTitle, {
            'title_id': 'title_id', 'genre_id': 'genre_id',
        }),
        ('review.csv', Review, {
            'title_id': 'title_id', 'text': 'text', 'author': 'author_id',
            'score': 'score', 'pub_date': 'pub_date',
        }),
        ('comments.csv', Comment, {
            'review_id': 'review_id', 'text': 'text', 'author': 'author_id',
            'pub_date': 'pub_date',
        }),
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Добавить каталог данных и режим строгой проверки."""
        parser.add_argument(
            '--path', type=Path, default=settings.BASE_DIR / 'static' / 'data',
            help='Каталог с семью CSV-файлами (по умолчанию static/data).',
        )
        parser.add_argument(
            '--strict', action='store_true',
            help='Отменить весь импорт при первой ошибке в данных.',
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Импортировать файлы по зависимостям и вывести общий результат."""
        directory = Path(options['path'])
        missing = [
            filename for filename, _, _ in self.IMPORTS
            if not (directory / filename).is_file()
        ]
        if missing:
            raise CommandError(f'Не найдены файлы: {", ".join(missing)}')
        totals: Counter[RowResult] = Counter()
        reports = []
        for filename, model, fields in self.IMPORTS:
            counts = self.import_file(
                directory / filename, model, fields, options['strict'],
            )
            totals.update(counts)
            reports.append((filename, counts))
        for filename, counts in reports:
            self.stdout.write(
                f'{filename}: добавлено {counts[RowResult.CREATED]}, '
                f'существующих {counts[RowResult.EXISTING]}, '
                f'ошибок {counts[RowResult.INVALID]}',
            )
        summary = (
            f'Импорт завершён: добавлено {totals[RowResult.CREATED]}, '
            f'существующих {totals[RowResult.EXISTING]}, '
            f'ошибок {totals[RowResult.INVALID]}.'
        )
        self.stdout.write(
            self.style.WARNING(summary) if totals[RowResult.INVALID]
            else self.style.SUCCESS(summary)
        )

    def import_file(
        self, path: Path, model: type[Model], fields: dict[str, str],
        strict: bool,
    ) -> Counter[RowResult]:
        """Проверить структуру CSV и посчитать результаты его строк."""
        counts: Counter[RowResult] = Counter()
        try:
            with path.open(encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source, strict=True)
                missing = {'id', *fields} - set(reader.fieldnames or [])
                if missing:
                    raise CommandError(
                        f'{path.name}: отсутствуют столбцы '
                        f'{", ".join(sorted(missing))}.',
                    )
                for row in reader:
                    result = self.import_row(
                        row, model, fields, path.name, reader.line_num, strict,
                    )
                    counts[result] += 1
        except (OSError, UnicodeError, csv.Error) as error:
            raise CommandError(f'Не удалось прочитать {path.name}: {error}')
        return counts

    def import_row(
        self, row: CSVRow, model: type[Model], fields: dict[str, str],
        filename: str, line_number: int, strict: bool,
    ) -> RowResult:
        """Откатить только ошибочную строку либо прервать строгий импорт."""
        try:
            with transaction.atomic():
                return self.save_row(row, model, fields)
        except (ValidationError, IntegrityError) as error:
            message = f'{filename}, строка {line_number}: {error}'
            if strict:
                raise CommandError(message) from error
            self.stderr.write(self.style.WARNING(message))
            return RowResult.INVALID

    @staticmethod
    def save_row(
        row: CSVRow, model: type[Model], fields: dict[str, str],
    ) -> RowResult:
        """Сохранить валидную строку, не перезаписывая существующий ID."""
        if None in row:
            raise ValidationError('Число значений превышает число столбцов.')
        raw_id = row.get('id')
        try:
            pk = int(raw_id)
        except (ValueError, TypeError) as error:
            raise ValidationError({
                'id': 'Ожидается целое число в строке CSV; '
                f'получен тип {type(raw_id).__name__}.',
            }) from error
        if pk <= 0:
            raise ValidationError({'id': 'ID должен быть положительным.'})
        missing = [name for name, value in row.items() if value is None]
        if missing:
            raise ValidationError({
                name: 'Ожидается строка CSV; получен NoneType.'
                for name in missing
            })
        if model.objects.filter(pk=pk).exists():
            return RowResult.EXISTING
        values = {
            target: row[source] for source, target in fields.items()
            if source in row
        }
        instance = model(pk=pk, **values)
        if isinstance(instance, User):
            instance.set_unusable_password()
        instance.full_clean()
        instance.save(force_insert=True)
        return RowResult.CREATED
