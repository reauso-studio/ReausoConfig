# Advanced Features

## Required Values with `_required_`

Mark config values that must be provided externally (via CLI, programmatic overrides, or environment variables):

```yaml
# config.yaml
_target_: app
api_key: _required_           # Must be provided
database_url: _required_      # Must be provided
port: 8080                    # Has default, optional

# With optional type hint
timeout:
  _required_: int             # Must be int when provided
```

Required values can be satisfied by:

- CLI overrides: `api_key=secret123` (when [enabled](composition.md#cli-overrides) with `rc.set_cli_overrides(True)`)
- Programmatic overrides: `overrides={"api_key": "secret"}`
- Environment variable interpolation: `api_key: ${env:API_KEY}`

```python
# This will raise RequiredValueError - api_key not provided
model = rc.instantiate(path=Path("config.yaml"))

# Provide required values via overrides
model = rc.instantiate(
    path=Path("config.yaml"),
    overrides={"api_key": "secret123", "database_url": "postgres://..."},
)

# Or validate first to check what's missing
result = rc.validate(path=Path("config.yaml"))
if not result.valid:
    for error in result.errors:
        print(error)  # Shows which _required_ values are missing
```

## Partial Instantiation

Instantiate only a specific section of the config tree:

```python
# Load trainer config, but only instantiate the model
model = rc.instantiate(path=Path("trainer.yaml"), inner_path="model")

# Works with nested paths
encoder = rc.instantiate(path=Path("trainer.yaml"), inner_path="model.encoder")

# And list indices
first_callback = rc.instantiate(path=Path("trainer.yaml"), inner_path="callbacks[0]")
```

**How it works:**

1. Incremental composition: Only files needed for `inner_path` and its dependencies are loaded
2. Overrides are applied to the relevant portions of the config
3. Interpolations (`${...}`) are resolved - dependencies outside `inner_path` are loaded as needed
4. The sub-config at `inner_path` is extracted and instantiated

This means interpolations can reference values outside the partial:

```yaml
# trainer.yaml
_target_: trainer
defaults:
  learning_rate: 0.01
model:
  _target_: model
  lr: ${/defaults.learning_rate}  # References outside model section
```

```python
# This works! Interpolation resolved before extraction
model = rc.instantiate(path=Path("trainer.yaml"), inner_path="model")
print(model.lr)  # 0.01
```

**Instance sharing with external targets:**

If the partial section has `_instance_` references to targets outside the section, those targets are automatically instantiated and shared:

```yaml
_target_: app
shared_cache:
  _target_: cache
  size: 100
services:
  api:
    _target_: service
    cache:
      _instance_: /shared_cache  # Outside "services.api" scope
```

```python
# Instantiates both the service AND the shared_cache it references
service = rc.instantiate(path=Path("app.yaml"), inner_path="services.api")
print(service.cache.size)  # 100
```

### Lazy Composition Optimization

When using `inner_path`, ReausoConfig automatically optimizes the composition process by only loading the files needed to resolve the requested section:

```yaml
# trainer.yaml - Large config with many sections
_target_: trainer
model:
  _ref_: ./models/resnet.yaml
  lr: ${/defaults.learning_rate}
data:
  _ref_: ./data/imagenet.yaml      # NOT loaded if inner_path="model"
callbacks:
  _ref_: ./callbacks/all.yaml       # NOT loaded if inner_path="model"
defaults:
  learning_rate: 0.01
```

```python
# Only loads: trainer.yaml, models/resnet.yaml
# Skips: data/imagenet.yaml, callbacks/all.yaml
model = rc.instantiate(path=Path("trainer.yaml"), inner_path="model")
```

The incremental composition algorithm:
1. Loads only the files needed to reach `inner_path`
2. Analyzes dependencies (interpolations like `${/defaults.learning_rate}`)
3. Loads additional files only for paths in the dependency closure
4. Skips all other `_ref_` markers entirely

This optimization is automatic and transparent - you get the same results with better performance for partial instantiation of large configs.

### Optional Root `_target_` with `inner_path`

When using `inner_path`, the root-level `_target_` is optional. This allows organizing configs as collections of components without requiring the root to be instantiable.

**When is `_target_` optional?**

A `_target_` is optional when rconfig can determine the type unambiguously:
- The section has an explicit `_target_`, OR
- The type can be inferred from the parent's field type hint (concrete type, not abstract, not a Union with multiple implementations)

```yaml
# experiment.yaml - No _target_ at root level
model:
  _target_: transformer
  encoder:           # No _target_, but Transformer.encoder has concrete type hint
    layers: 12
    hidden_size: 768

training:
  _target_: trainer
  epochs: 100

data:  # No _target_ - just raw config values
  path: "/datasets/train"
  batch_size: 32
```

```python
# Works - model section has _target_
model = rc.instantiate(Path("experiment.yaml"), inner_path="model")

# Works - encoder type inferred from Transformer.encoder type hint
encoder = rc.instantiate(Path("experiment.yaml"), inner_path="model.encoder")

# Works - training section has _target_
trainer = rc.instantiate(Path("experiment.yaml"), inner_path="training")

# Raises AmbiguousTargetError - data has no _target_ and no parent to infer from
rc.instantiate(Path("experiment.yaml"), inner_path="data")

# Raises AmbiguousTargetError - root has no _target_
rc.instantiate(Path("experiment.yaml"))
```

**Type inference from parent:**

When extracting a nested path like `model.encoder`, rconfig checks if the parent (`model`) has a `_target_` and whether that class has a concrete type hint for the field (`encoder`). If so, the type is automatically inferred.

```python
@dataclass
class Encoder:
    layers: int

@dataclass
class Transformer:
    encoder: Encoder  # Concrete type hint - can be inferred

rc.register("transformer", Transformer)
rc.register("encoder", Encoder)

# Config without _target_ on encoder
# model:
#   _target_: transformer
#   encoder:
#     layers: 12

# Type is inferred from Transformer.encoder type hint
encoder = rc.instantiate(Path("model.yaml"), inner_path="model.encoder")
```

**List element type inference:**

Type inference also works for list indices by extracting the element type from `list[X]` type hints:

```python
@dataclass
class Callback:
    name: str

@dataclass
class Trainer:
    callbacks: list[Callback]  # list[X] type hint

rc.register("trainer", Trainer)
rc.register("callback", Callback)

# Config with list of callbacks (no _target_ on elements)
# trainer:
#   _target_: trainer
#   callbacks:
#     - name: early_stopping
#     - name: checkpointing

# Type is inferred from list[Callback] element type
callback = rc.instantiate(Path("trainer.yaml"), inner_path="trainer.callbacks[0]")
assert isinstance(callback, Callback)
```

**Dict element type inference:**

Type inference works for dict values by extracting the value type from `dict[str, X]` type hints:

```python
@dataclass
class ModelConfig:
    hidden_size: int

@dataclass
class Registry:
    models: dict[str, ModelConfig]  # dict[str, X] type hint

rc.register("registry", Registry)
rc.register("model_config", ModelConfig)

# Config with dict values (no _target_ on values)
# registry:
#   _target_: registry
#   models:
#     resnet:
#       hidden_size: 512
#     vgg:
#       hidden_size: 256

# Type is inferred from dict[str, ModelConfig] value type
registry = rc.instantiate(Path("registry.yaml"))
assert isinstance(registry.models["resnet"], ModelConfig)
```

**Tuple positional type inference:**

Type inference works for tuple elements by matching the position to the corresponding type in `tuple[A, B, C]` type hints:

```python
@dataclass
class Encoder:
    hidden_size: int

@dataclass
class Decoder:
    output_size: int

@dataclass
class Pipeline:
    components: tuple[Encoder, Decoder]  # Positional types

rc.register("pipeline", Pipeline)
rc.register("encoder", Encoder)
rc.register("decoder", Decoder)

# Config: components[0] -> Encoder, components[1] -> Decoder
# pipeline:
#   _target_: pipeline
#   components:
#     - hidden_size: 512
#     - output_size: 256
```

Variadic tuples (`tuple[X, ...]`) work like lists — all elements share the same type.

**Annotated type unwrapping:**

`Annotated[X, metadata]` wrappers are stripped before type inference:

```python
@dataclass
class Scheduler:
    step_size: int

@dataclass
class Trainer:
    scheduler: Annotated[Scheduler, "learning rate scheduler"]

rc.register("trainer", Trainer)
rc.register("scheduler", Scheduler)

# Annotated is unwrapped — inference sees Scheduler
trainer = rc.instantiate(Path("trainer.yaml"))
assert isinstance(trainer.scheduler, Scheduler)
```

This composes with other wrappers: `Annotated[Optional[list[X]], meta]` correctly unwraps through all layers.

**Optional container unwrapping:**

`Optional[container]` types are unwrapped to expose the inner container for inference:

```python
@dataclass
class Trainer:
    callbacks: Optional[list[Callback]]  # Optional is unwrapped

rc.register("trainer", Trainer)
rc.register("callback", Callback)

# Optional[list[Callback]] unwraps to list[Callback], then to Callback
trainer = rc.instantiate(Path("trainer.yaml"))
assert isinstance(trainer.callbacks[0], Callback)
```

**Union type inference (structural matching):**

When a field has a union type like `Union[A, B]`, rconfig resolves it via structural matching — comparing the config keys against each candidate's constructor parameters:

```python
@dataclass
class SGDOptimizer:
    lr: float
    momentum: float = 0.9

@dataclass
class AdamOptimizer:
    lr: float
    eps: float = 1e-8

@dataclass
class Model:
    optimizer: Union[SGDOptimizer, AdamOptimizer]

rc.register("model", Model)
rc.register("sgd", SGDOptimizer)
rc.register("adam", AdamOptimizer)

# Config with momentum -> matches SGDOptimizer
# model:
#   _target_: model
#   optimizer:
#     lr: 0.01
#     momentum: 0.95

model = rc.instantiate(Path("model.yaml"))
assert isinstance(model.optimizer, SGDOptimizer)
```

Structural matching checks: required fields present, no unknown keys (unless `**kwargs`), and value type compatibility. Abstract union members are expanded to their concrete subclasses. Ambiguous matches (0 or 2+ candidates) leave the value as a plain dict.

**`set[X]` / `frozenset[X]` element type inference:**

YAML has no native set type — set-typed fields receive list values. The element type is extracted from `set[X]` or `frozenset[X]` type hints for inference:

```python
@dataclass
class Tag:
    name: str

@dataclass
class Article:
    tags: set[Tag]  # Element type extracted from set[Tag]

rc.register("article", Article)
rc.register("tag", Tag)

# YAML list items inferred as Tag via set[Tag] hint
article = rc.instantiate(Path("article.yaml"))
for tag in article.tags:
    assert isinstance(tag, Tag)
```

**`Sequence[X]` / `Mapping[K, V]` abstract collection ABCs:**

Abstract collection types from `collections.abc` are handled as aliases for their concrete counterparts:

```python
from collections.abc import Sequence, Mapping

@dataclass
class Pipeline:
    steps: Sequence[Step]  # Treated like list[Step]

@dataclass
class ServiceRegistry:
    services: Mapping[str, Endpoint]  # Treated like dict[str, Endpoint]
```

Supported ABCs: `Sequence`, `MutableSequence`, `Set`, `MutableSet`, `Mapping`, `MutableMapping`.

**`NewType` unwrapping:**

`NewType` aliases are unwrapped to expose the underlying type for inference:

```python
from typing import NewType

DatabaseConfig = NewType("DatabaseConfig", DatabaseConnection)

@dataclass
class AppConfig:
    database: DatabaseConfig  # Unwrapped to DatabaseConnection

rc.register("app_config", AppConfig)
rc.register("databaseconnection", DatabaseConnection)

# NewType is transparent — inference sees DatabaseConnection
app = rc.instantiate(Path("app.yaml"))
assert isinstance(app.database, DatabaseConnection)
```

**Note:** `inner_path=None` is equivalent to `inner_path="/"` (root). The root always requires `_target_` because there's no parent to infer the type from.

### Multi-Environment Configuration

Use `inner_path` to select environment-specific sections from a single config file:

```yaml
# environments.yaml
development:
  _target_: app_config
  database:
    host: localhost
    port: 5432
  debug: true
  log_level: DEBUG

staging:
  _target_: app_config
  database:
    host: staging-db.internal
    port: 5432
  debug: false
  log_level: INFO

production:
  _target_: app_config
  database:
    host: ${env:DATABASE_HOST}
    port: '${env:DATABASE_PORT ?: 5432}'  # "5433" from env becomes int 5433
  debug: false
  log_level: WARNING
```

```python
import os
import rconfig as rc
from pathlib import Path

# Select environment from env var (defaults to "development")
env = os.getenv("APP_ENV", "development")

config = rc.instantiate(
    path=Path("environments.yaml"),
    inner_path=env,
)

print(config.database.host)  # "localhost" in dev, env var in prod
print(config.debug)          # True in dev, False in prod
```

This approach provides:
- **Single file**: All environments visible in one place for easy comparison
- **Environment variable selection**: `APP_ENV=production python main.py`
- **CLI override**: `python main.py inner_path=staging`
- **Dynamic values**: Use `${env:...}` interpolation for production secrets

## Lazy Instantiation

Delay object creation until first attribute access. Useful for expensive initialization (loading models, database connections) that may not always be used.

### Global Lazy Mode

Make all nested configs lazy:

```python
# All nested objects delay __init__ until first access
trainer = rc.instantiate(path=Path("trainer.yaml"), lazy=True)

# trainer.model is lazy - __init__ not called yet
print(rc.is_lazy_proxy(obj=trainer.model))  # True

# Accessing any attribute triggers initialization
print(trainer.model.hidden_size)  # NOW model.__init__ is called
print(rc.is_lazy_proxy(obj=trainer.model))  # False
```

### Per-Field Lazy Mode

Mark specific fields as lazy in YAML:

```yaml
_target_: trainer
model:
  _target_: model
  _lazy_: true  # Only model is lazy
  hidden_size: 256
optimizer:
  _target_: optimizer  # optimizer is eager (normal)
  lr: 0.001
```

```python
trainer = rc.instantiate(path=Path("trainer.yaml"))
print(rc.is_lazy_proxy(obj=trainer.model))      # True - lazy
print(rc.is_lazy_proxy(obj=trainer.optimizer))  # False - eager
```

**Note:** `_lazy_: true` only affects that specific field, not its children (non-cascading).

### Checking Lazy Status

```python
from rconfig import is_lazy_proxy, force_initialize

trainer = rc.instantiate(path=Path("trainer.yaml"), lazy=True)

# Check if object is uninitialized
if is_lazy_proxy(trainer.model):
    print("Model not yet initialized")

# Force initialization without accessing attributes
force_initialize(trainer.model)
print(is_lazy_proxy(trainer.model))  # False
```

### How It Works

- Lazy proxies are dynamic subclasses of your target class
- `isinstance(lazy_obj, TargetClass)` returns `True`
- After initialization, the object behaves identically to an eager instance
- Works correctly with `_instance_` sharing - all references share the same lazy proxy
- **No framework dependency in user code**: The returned objects work without importing anything from rconfig

### Transparency Guarantees

Lazy proxies are designed to be completely transparent to user code:

| Operation                    | Works? | Notes                                  |
| ---------------------------- | ------ | -------------------------------------- |
| `isinstance(obj, MyClass)` | Yes    | Proxy is a subclass of your class      |
| `obj.attribute`            | Yes    | Triggers init, then returns value      |
| `obj.method()`             | Yes    | Triggers init, then calls method       |
| `hasattr(obj, 'attr')`     | Yes    | Triggers init, then checks             |
| `len(obj)`                 | Yes    | Triggers init, then calls `__len__`  |
| `for x in obj`             | Yes    | Triggers init, then iterates           |
| `obj[key]`                 | Yes    | Triggers init, then indexes            |
| `obj()`                    | Yes    | Triggers init, then calls `__call__` |
| `dataclasses.asdict(obj)`  | Yes    | Triggers init, then converts           |
| `str(obj)` / `repr(obj)` | Yes    | Triggers init, then formats            |

### Known Limitations

These edge cases behave differently from regular objects:

| Operation                    | Behavior            | Workaround                       |
| ---------------------------- | ------------------- | -------------------------------- |
| `type(obj)`                | Returns proxy class | Use `isinstance()` instead     |
| `obj.__class__`            | Returns proxy class | Use `isinstance()` instead     |
| `obj.__class__ == MyClass` | Returns `False`   | Use `isinstance(obj, MyClass)` |

**Impact**: These limitations only affect code that uses `type()` or `__class__` for exact type comparison. This is rare in practice - most code uses `isinstance()` which works correctly.

### Use Cases

1. **Expensive resources**: Models that load weights, database connections
2. **Conditional initialization**: Components only needed in certain code paths
3. **Faster startup**: Defer heavy initialization until actually needed

```yaml
_target_: app
# Large model only loaded if inference is called
inference_model:
  _target_: llm
  _lazy_: true
  model_path: /path/to/large_model.bin

# Always needed
config:
  _target_: config
  debug: false
```

## Immutable / Frozen Configs

ReausoConfig supports immutable configurations through Python's native immutability features. Since the library instantiates your classes directly by calling their constructors, immutability is controlled through your class design - not a library parameter.

### Why No `freeze=True` Parameter?

Unlike some configuration libraries that wrap config objects to enforce immutability, ReausoConfig:

- Instantiates your classes directly - no wrapping or proxying
- Returns pure Python objects with no framework dependency
- Lets Python enforce immutability at the language level

This design means you get IDE autocompletion, static type checking, and zero runtime overhead for immutability.

### Using Frozen Dataclasses

The recommended approach for immutable configs:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelConfig:
    hidden_size: int
    dropout: float = 0.1

@dataclass(frozen=True)
class TrainerConfig:
    model: ModelConfig
    epochs: int
```

```yaml
# config.yaml
_target_: trainer
model:
  _target_: model
  hidden_size: 256
epochs: 100
```

```python
import rconfig as rc

rc.register(name="model", target=ModelConfig)
rc.register(name="trainer", target=TrainerConfig)

trainer = rc.instantiate(path=Path("config.yaml"))

# Attempting to modify raises FrozenInstanceError
trainer.epochs = 200  # FrozenInstanceError!
trainer.model.hidden_size = 512  # FrozenInstanceError!
```

### Using Pydantic Frozen Models

Pydantic models can also be frozen:

```python
from pydantic import BaseModel, ConfigDict

class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    hidden_size: int
    dropout: float = 0.1

class TrainerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: ModelConfig
    epochs: int
```

### Other Immutability Options

Python provides several built-in options for immutable objects:

| Approach         | Example                      | Notes                      |
| ---------------- | ---------------------------- | -------------------------- |
| Frozen dataclass | `@dataclass(frozen=True)`  | Recommended for most cases |
| Pydantic frozen  | `ConfigDict(frozen=True)`  | With Pydantic validation   |
| attrs frozen     | `@attrs.frozen`            | attrs library              |
| NamedTuple       | `class Config(NamedTuple)` | Inherently immutable       |

### Benefits of User-Controlled Immutability

- **IDE Support**: Full autocompletion and type checking
- **Static Analysis**: mypy/pyright catch mutation attempts before runtime
- **No Runtime Overhead**: Python enforces immutability, not the library
- **Flexibility**: Mix mutable and immutable classes as needed
- **Framework Independence**: Works with any immutability pattern you prefer
