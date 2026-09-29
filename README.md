# Commonplace

Commonplace is a small Django social application with server-rendered HTML/CSS. It supports member accounts, posts and image uploads, following and reshares, plus ad-manager campaigns with simulated funding.

## Requirements

- Python 3.12 or newer
- `pip`

## Local Setup

From a terminal, clone the repository and enter the project directory:

```sh
git clone <repository-url>
cd social-vibecode
```

Create a virtual environment, install the project dependencies, and apply the included migrations:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
```

The example uses the `python3.12` executable. If your installed Python is 3.12 or newer but uses another command name (for example, `python3.13`), substitute that name when creating the environment.

Create an administrator account and start Django's development server:

```sh
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

On Windows PowerShell, use `py -3.12 -m venv .venv` and activate with `.\.venv\Scripts\Activate.ps1`; the remaining `python` commands are the same.

Open `http://127.0.0.1:8000/accounts/register/` to register a member, then log in at `http://127.0.0.1:8000/accounts/login/`. The feed is at `http://127.0.0.1:8000/`, and Django admin is at `http://127.0.0.1:8000/admin/`.

## First Ad Manager

Public registration always creates a `member`; the registration form does not accept an account role. To enable campaign management locally, sign in to Django admin as a superuser, open Users, and change the intended account's type to `ad_manager`. The user can then open `/ads/`, create a campaign and creative, and add simulated funds. New creatives require staff approval in admin before the feed considers them eligible.

For optional sample social content, run:

```sh
python manage.py seed_social_data
```

The command is available only when `DEBUG=True`. It creates repeatable demo members with unusable passwords, sample posts, an image, follows, and a reshare. Register or create accounts separately if you need to log in as those users.

## Local Data and Media

The default database is SQLite. `python manage.py migrate` creates `db.sqlite3`, which is ignored by Git. Uploaded post and creative images are stored under the local `media/` directory and are served by Django only during development. Both the database and media directory contain local application data and should not be committed.

This checkout's `STATIC_URL` is configured for the current cloud IDE mount at `/proxy/8000/static/`. The debug URL configuration serves both that prefixed path and the standard `/static/` path. Cloud IDEs with a different proxy port or mount path may need matching `STATIC_URL`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS` settings.

## Tests and Checks

With the virtual environment active, run:

```sh
python manage.py test
python manage.py check
python manage.py migrate --check
python manage.py makemigrations --check --dry-run
```

## Production Limitations

The checked-in Django secret key and `DEBUG=True` are for local development only. Before deployment, configure a private secret key, disable debug mode, set a narrow `ALLOWED_HOSTS` list and the deployment's CSRF trusted origins, and use PostgreSQL for concurrent campaign-budget updates. Configure durable object storage for media. Campaign purchases are simulated; no payment provider or real card processing is connected.
