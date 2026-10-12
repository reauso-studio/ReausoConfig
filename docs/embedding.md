# Using ReausoConfig in an Application

ReausoConfig is not only for command-line scripts. You can load configuration inside a web application (for example a Django `settings.py`), a background worker, or a test run. This page covers what to keep in mind when ReausoConfig is a library inside a larger program.

## `sys.argv` Belongs to the Host Program

In an application, the command line belongs to the host: `python manage.py runserver 0.0.0.0:8000`, `celery -A proj worker`, or `pytest -k slow`. ReausoConfig therefore **never reads `sys.argv` by default**:

- `key=value` arguments are not applied as config overrides.
- `--help`/`-h` does not trigger the config help (and is not removed from `sys.argv`).

Nothing needs to be disabled for application or test use.

## Opting In for Scripts

For training scripts and other command-line tools where config overrides from the command line are wanted, enable them once at program start:

```python
import rconfig as rc

rc.set_cli_overrides(True)

trainer = rc.instantiate(path="config.yaml")  # python train.py model.lr=0.01
```

`rc.cli_overrides_enabled()` returns the current setting. A per-call argument takes precedence over the process-wide setting:

```python
rc.instantiate(path="config.yaml", cli_overrides=True)   # Read sys.argv for this call only
rc.instantiate(path="config.yaml", cli_overrides=False)  # Ignore sys.argv even if enabled globally
```

## Environment-Driven Configuration

Applications are usually configured through environment variables. Use `${env:...}` with a [coalesce default](interpolation.md#coalesce-operators); values are [converted to the declared field types](type-coercion.md), so `DEBUG=false` becomes `False` for a `bool` field and `ALLOWED_HOSTS=a.com, b.com` becomes a list for a `list[str]` field.

Environment variables are re-read on every load. The composition cache only caches parsed files, never resolved environment values, so a changed variable is picked up the next time you call `rc.instantiate()`.

## Registration

Only the root dataclass must be registered. Nested dataclass fields need neither `rc.register()` nor `_target_`: the class is [inferred from the parent's type hint](object-instantiation.md#target-resolution) as long as it is concrete (not abstract and without multiple registered subclasses).

Registering the same target (or resolver) again is harmless, so module-level `rc.register()` calls are safe when a module is reloaded (for example by a development server's autoreloader).

## Example: Django Settings

```python
# myproject/app_config.py
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    name: str
    host: str
    port: int


@dataclass
class AppConfig:
    debug: bool
    secret_key: str
    allowed_hosts: list[str]
    database: DatabaseConfig  # Inferred - no register() or _target_ needed
```

```yaml
# config.yaml
_target_: app_config
debug: '${env:DJANGO_DEBUG ?: false}'
secret_key: '${env:DJANGO_SECRET_KEY}'
allowed_hosts: '${env:DJANGO_ALLOWED_HOSTS ?: "localhost"}'
database:
  name: '${env:DB_NAME ?: "app"}'
  host: '${env:DB_HOST ?: "localhost"}'
  port: '${env:DB_PORT ?: 5432}'
```

```python
# myproject/settings.py
from pathlib import Path

import rconfig as rc

from myproject.app_config import AppConfig

BASE_DIR = Path(__file__).resolve().parent.parent

rc.register(name="app_config", target=AppConfig)
_config = rc.instantiate(path=BASE_DIR / "config.yaml", expected_type=AppConfig)

DEBUG = _config.debug
SECRET_KEY = _config.secret_key
ALLOWED_HOSTS = _config.allowed_hosts
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _config.database.name,
        "HOST": _config.database.host,
        "PORT": _config.database.port,
    }
}
```

`python manage.py runserver` and `manage.py test` arguments are never interpreted as config overrides, and a missing `DJANGO_SECRET_KEY` fails at startup with an `EnvironmentVariableError`.

## Failing Resolvers Are Not Swallowed by `?:`

The Elvis operator `?:` only falls back for `None` and for unset (or empty) environment variables. If a [custom resolver](interpolation.md#custom-resolvers) raises, the error propagates as `ResolverExecutionError`, with the original exception in `.original_error`:

```python
try:
    config = rc.instantiate(path="config.yaml")  # value: '${app:fetch_secret ?: "dev"}'
except rc.ResolverExecutionError as e:
    log.error("Secret lookup failed: %r", e.original_error)
    raise
```

Use `??` instead of `?:` if any resolver error should fall back to the default.
