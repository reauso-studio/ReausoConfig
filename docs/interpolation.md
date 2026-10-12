# Interpolation & Resolvers

## Interpolation

Reference config values and environment variables with `${...}` syntax:

```yaml
_target_: trainer
defaults:
  learning_rate: 0.01
  batch_size: 32

model:
  _target_: model
  lr: ${/defaults.learning_rate}     # Reference another config value
  scaled_lr: ${/defaults.learning_rate * 10}  # Arithmetic expressions

training:
  effective_batch: ${/defaults.batch_size * 4}
  output_dir: '${env:OUTPUT_DIR ?: "./output"}'  # Environment variable with default
  user_path: /data/${env:USER}/runs       # Embedded in string
```

### Config Path References

| Syntax   | Example                 | Description                  |
| -------- | ----------------------- | ---------------------------- |
| Absolute | `${/model.lr}`        | From root of composed config |
| Relative | `${./local.value}`    | From current document root   |
| Implicit | `${model.lr}`         | Same as relative             |
| Parent   | `${../sibling.value}` | Parent-relative path         |

### Environment Variables

```yaml
# Required (raises error if not set)
data_path: ${env:DATA_PATH}

# With default value (coalesce operator; string defaults need double quotes)
log_level: '${env:LOG_LEVEL ?: "INFO"}'
port: '${env:PORT ?: 8080}'      # Number default; PORT=9000 becomes 9000 for an int field
debug: '${env:DEBUG ?: false}'   # Bool default; DEBUG=true becomes True for a bool field
```

Defaults use the [coalesce operators](#coalesce-operators) `?:` and `??`. Quote the whole value in YAML, because `?: ` would otherwise be read as YAML syntax.

Environment variables are always strings. When the field has a declared type (`int`, `bool`, an enum, `list[str]`, ...), the value is converted to it after interpolation, see [Type Coercion](type-coercion.md). Fields typed `str` or without a type hint keep the string.

!!! warning "Inside expressions, environment values are still strings"
    Conversion applies to a field's final value, not inside an expression. In `${env:USE_GPU ?: false ? "cuda:0" : "cpu"}`, the value `"false"` is a non-empty string and selects `"cuda:0"`. Compare explicitly instead: `${(env:USE_GPU ?: "false") == "true" ? "cuda:0" : "cpu"}`. See [Values Inside Expressions](type-coercion.md#values-inside-expressions).

!!! note "Empty variables count as unset"
    A variable that is set but empty (`VAR=` in a `.env` file) is treated like an unset one: `${env:VAR}` raises `EnvironmentVariableError` and `${env:VAR ?: "default"}` falls back to the default.

### Expression Support

Full Python-like expression evaluation:

```yaml
# Arithmetic
doubled: ${/learning_rate * 2}
ratio: ${/a / /b}
power: ${/base ** 2}

# Comparisons
is_large: ${/epochs > 100}
is_valid: ${/lr >= 0.001 and /lr <= 1.0}

# Boolean
enabled: ${/use_gpu and not /debug_mode}

# String concatenation
filename: ${"model_" + /name + "_v" + /version}
```

### List Operations

```yaml
items: [1, 2, 3, 4, 5]
callbacks: [logger, checkpoint, early_stop]

# Indexing and slicing
first: ${/items[0]}          # 1
last: ${/items[-1]}          # 5
subset: ${/items[1:3]}       # [2, 3]
from_start: ${/items[:3]}    # [1, 2, 3]
to_end: ${/items[2:]}        # [3, 4, 5]

# Concatenation
all: ${/base_list + /extra_list}

# Removal by value
filtered: ${/callbacks - ["early_stop"]}  # [logger, checkpoint]

# Remove by index
without_first: ${/items.remove(0)}  # [2, 3, 4, 5]

# Length
count: ${len(/items)}  # 5

# Membership
has_gpu: ${"gpu" in /devices}
```

### Conditional Expressions

#### Ternary Operator

Conditional expressions using `condition ? if_true : if_false` syntax:

```yaml
# Basic ternary with boolean
mode: '${/debug ? "verbose" : "quiet"}'

# With comparison
level: '${/count > 10 ? "high" : "low"}'

# With resolver as condition
status: '${app:is_ready() ? "go" : "wait"}'

# Nested ternary (right-associative)
result: '${/a ? "first" : /b ? "second" : "third"}'
```

#### Coalesce Operators

Two coalesce operators for handling null values and errors:

| Operator | Name         | Catches                                                  |
| -------- | ------------ | -------------------------------------------------------- |
| `?:`   | Elvis (soft) | `None`, missing resolver/env                           |
| `??`   | Error (hard) | `None`, missing resolver/env, **all exceptions** |

```yaml
# Elvis coalesce - catches null and missing
safe_id: '${app:uuid ?: "fallback-id"}'
env_val: '${env:API_KEY ?: "dev-key"}'

# Error coalesce - also catches exceptions
risky_value: '${app:might_fail() ?? "safe-default"}'

# Chained coalesce (right-associative)
value: '${app:primary() ?? app:backup() ?? "ultimate-fallback"}'

# Combined with ternary
result: '${(app:get_value() ?? 0) > 5 ? "high" : "low"}'
```

**Elvis (`?:`) vs Error (`??`) Coalesce:**

- Use `?:` when you want resolver exceptions to propagate (fail fast)
- Use `??` when you want to catch all errors and use a fallback

```yaml
# ?: propagates errors from app:risky
critical: '${app:risky() ?: "fallback"}'  # Raises if risky() throws

# ?? catches all errors
safe: '${app:risky() ?? "fallback"}'  # Returns "fallback" if risky() throws
```

### Type Behavior

- **Standalone** `${expr}`: Preserves type (number stays number)
- **Embedded** `"text ${expr} more"`: Result is always string

```yaml
# Standalone - type preserved
lr: ${/defaults.learning_rate}     # float: 0.01
count: ${len(/items)}               # int: 5
enabled: ${/use_gpu}                # bool: true

# Embedded - becomes string
message: "Learning rate is ${/defaults.learning_rate}"  # str: "Learning rate is 0.01"
```

### Circular Reference Detection

Circular references are detected and raise `CircularInterpolationError`:

```yaml
# This will raise an error
a: ${/b}
b: ${/a}  # Circular: a -> b -> a
```

## Custom Resolvers

Register Python functions that can be called from interpolation expressions using the `app:` prefix:

```python
import rconfig as rc
from datetime import datetime
import uuid

# Simple resolver (no arguments)
@rc.resolver("uuid")
def gen_uuid() -> str:
    return str(uuid.uuid4())

# Resolver with arguments
@rc.resolver("now")
def now(fmt: str = "%Y-%m-%d") -> str:
    return datetime.now().strftime(fmt)

# Namespaced resolver - all three syntaxes are equivalent:
@rc.resolver("db", "lookup")      # Multiple arguments
@rc.resolver("db:lookup")         # Colon-delimited string
@rc.resolver("db.lookup")         # Dot-delimited string
def db_lookup(table: str, id: int) -> dict:
    return database.get(table, id)

# Deeply nested namespace
@rc.resolver("db", "cache", "get")  # or "db:cache:get" or "db.cache.get"
def cache_get(key: str, ttl: int = 60) -> Any:
    return cache.get(key, ttl=ttl)

# Resolver with config access (special _config_ parameter)
@rc.resolver("derive")
def derive(path: str, *, _config_: dict) -> Any:
    return _config_.get(path)
```

### Resolver Syntax

```yaml
_target_: experiment

# No arguments (parentheses optional)
id: '${app:uuid}'
id_alt: '${app:uuid()}'  # Also valid

# Positional arguments
timestamp: '${app:now("%Y-%m-%d_%H-%M-%S")}'

# Keyword arguments
timestamp2: '${app:now(fmt="%Y-%m-%d")}'

# Namespaced resolver with arguments
user: '${app:db:lookup("users", 42)}'

# Deep namespace with kwargs
cached: '${app:db:cache:get("session", ttl=300)}'

# Config reference as argument
base_lr: 0.01
scaled_lr: '${app:scale(/base_lr, 2)}'

# Expression as argument
doubled: '${app:math:multiply(/base_lr, 2)}'
```

### Config Access in Resolvers

Resolvers can access the full config by declaring a `_config_` keyword-only parameter:

```python
@rc.resolver("derive")
def derive(key: str, *, _config_: dict) -> Any:
    """Access config values from within a resolver."""
    return _config_.get(key)
```

The `_config_` parameter receives a read-only view of the raw config dictionary (before instantiation).

**Note:** Resolvers can be used with conditional expressions (ternary `?:`, coalesce `?:` and `??`). See [Conditional Expressions](#conditional-expressions) for details.

### Unregistering Resolvers

```python
# Unregister a resolver
rc.unregister_resolver("uuid")
rc.unregister_resolver("db", "lookup")  # Namespaced
```
