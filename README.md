# YaMDb API

YaMDb — API для каталога произведений. Пользователи могут читать данные о
категориях, жанрах и произведениях, публиковать отзывы с оценками и оставлять
комментарии. Администраторы управляют каталогом и учётными записями,
модераторы редактируют и удаляют пользовательские публикации.

## Технологии

- Python 3.10+
- Django и Django REST framework
- Simple JWT
- SQLite (по умолчанию)

## Запуск проекта

Клонируйте репозиторий и создайте виртуальное окружение:

```bash
python -m venv venv
```

Активируйте его и установите зависимости. В Windows используйте
`venv\Scripts\activate`, в macOS и Linux — `source venv/bin/activate`.

```bash
pip install -r requirements.txt
cd api_yamdb
python manage.py migrate
python manage.py import_csv
python manage.py runserver
```

После запуска документация доступна по адресу `http://127.0.0.1:8000/redoc/`.

## Примеры запросов

Получить список произведений:

```http
GET /api/v1/titles/
```

Зарегистрировать пользователя:

```http
POST /api/v1/auth/signup/
Content-Type: application/json

{
  "email": "reader@example.com",
  "username": "reader"
}
```

Успешный ответ содержит переданные `email` и `username`. Код подтверждения
отправляется на электронную почту. Чтобы получить JWT-токен, передайте
`username` и `confirmation_code` на `POST /api/v1/auth/token/`:

```json
{
  "token": "<JWT-токен>"
}
```

## Автор

Репозиторий ведёт [19agR](https://github.com/19agR).
