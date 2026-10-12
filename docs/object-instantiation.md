# Object Instantiation

ReausoConfig's key feature is **object-oriented configuration**: your config files describe object relationships, and the library instantiates a fully-connected object graph by calling actual class constructors.

This enables **full object instantiation** - not just data containers, but factories, service objects, logic components, and complete application wiring. Your entire application can be assembled from configuration.

## How It Works

When you call `rc.instantiate()`:

1. **Config loading**: The config file is loaded and composed (resolving [`_ref_`](composition.md) references)
2. **Validation**: The config structure is validated against registered class constructors
3. **Recursive instantiation**: Each nested config with a [`_target_`](core-concepts.md#the-_target_-key) becomes an actual object instance
4. **Constructor mapping**: Config keys become constructor keyword arguments

```python
@dataclass
class Database:
    host: str
    port: int

@dataclass
class Service:
    name: str
    db: Database  # Nested object

rc.register(name="database", target=Database)
rc.register(name="service", target=Service)
```

```yaml
# service.yaml
_target_: service
name: "api"
db:
  _target_: database
  host: "localhost"
  port: 5432
```

```python
# This creates: Service(name="api", db=Database(host="localhost", port=5432))
service = rc.instantiate(path=Path("service.yaml"))

# Result is pure Python objects - no framework dependency
assert isinstance(service, Service)
assert isinstance(service.db, Database)
assert service.db.host == "localhost"
```

## Beyond Data Classes: Factories and Logic Objects

ReausoConfig works with **any callable** - not just dataclasses. Constructor parameters don't need to be stored as attributes. This makes it perfect for factories, builders, and objects that perform logic during initialization:

```python
class Rectangle:
    """Constructor values are used for computation, not stored directly."""
    def __init__(self, width: float, height: float):
        self._area = width * height
        self._perimeter = 2 * (width + height)

    @property
    def area(self) -> float:
        return self._area

class ConnectionPool:
    """Factory that creates internal resources from config values."""
    def __init__(self, host: str, port: int, pool_size: int):
        self._connections = [
            self._create_connection(host, port)
            for _ in range(pool_size)
        ]

    def _create_connection(self, host: str, port: int):
        # Create actual connection...
        pass

class ApplicationBootstrapper:
    """Orchestrates application startup from config."""
    def __init__(self, db: ConnectionPool, cache: ConnectionPool, workers: int):
        self._db = db
        self._cache = cache
        self._start_workers(workers)

    def _start_workers(self, count: int):
        # Initialize worker threads...
        pass

rc.register(name="rectangle", target=Rectangle)
rc.register(name="pool", target=ConnectionPool)
rc.register(name="app", target=ApplicationBootstrapper)
```

```yaml
# app.yaml - Wire your entire application from config
_target_: app
workers: 4
db:
  _target_: pool
  host: "db.example.com"
  port: 5432
  pool_size: 10
cache:
  _target_: pool
  host: "cache.example.com"
  port: 6379
  pool_size: 5
```

```python
# One call bootstraps your entire application
app = rc.instantiate(path=Path("app.yaml"))
```

## Type-Driven Polymorphism

Type hints enable runtime substitution of implementations:

```python
from abc import ABC, abstractmethod

class Optimizer(ABC):
    @abstractmethod
    def step(self): pass

class Adam(Optimizer):
    def __init__(self, lr: float):
        self.lr = lr
    def step(self): pass

class SGD(Optimizer):
    def __init__(self, lr: float, momentum: float):
        self.lr = lr
        self.momentum = momentum
    def step(self): pass

@dataclass
class Trainer:
    optimizer: Optimizer  # Accepts any Optimizer subclass

rc.register(name="adam", target=Adam)
rc.register(name="sgd", target=SGD)
rc.register(name="trainer", target=Trainer)
```

```yaml
# Switch implementations by changing _target_ - no code changes needed
_target_: trainer
optimizer:
  _target_: adam  # or "sgd"
  lr: 0.001
```

## Framework Independence

After instantiation, your objects have **no dependency on ReausoConfig**:

- Objects are pure Python instances of your classes
- No base classes or mixins required
- No framework imports needed in your application code
- Works with dataclasses, regular classes, or any callable

This means your application code remains clean and testable - only your startup/configuration code needs to import rconfig.

## Nested Configs

Configs can contain nested configs that are instantiated recursively:

```yaml
_target_: trainer
model:
  _target_: model
  hidden_size: 256
optimizer:
  _target_: optimizer
  lr: 0.001
```

### Target Resolution

ReausoConfig can automatically determine the target class for nested configs in two ways:

#### 1. Implicit Inference from Type Hints

When a nested config field has a concrete type hint (a class that is not abstract and has no ambiguous registered subclasses), the `_target_` can be omitted and the class is inferred from the type hint. The nested class does **not** need to be registered: it is registered automatically. Only the root target needs `rc.register()`:

```python
@dataclass
class ModelConfig:
    hidden_size: int

@dataclass
class TrainerConfig:
    model: ModelConfig  # Concrete type - _target_ can be inferred
    epochs: int

rc.register(name="trainer", target=TrainerConfig)
# ModelConfig needs no registration - it is inferred from the type hint
```

```yaml
# _target_ for model is optional here
_target_: trainer
model:
  hidden_size: 256  # No _target_ needed - inferred from type hint
epochs: 10
```

#### 2. Auto-registration from Explicit Targets

When a nested config has an explicit `_target_` that matches the expected type's class name (case-insensitive), the class is automatically registered if not already:

```python
@dataclass
class ResNet:
    layers: int
    pretrained: bool

@dataclass
class TrainerConfig:
    model: ResNet  # Type hint provides the class
    epochs: int

rc.register(name="trainer", target=TrainerConfig)
# Note: ResNet is NOT registered manually
```

```yaml
_target_: trainer
model:
  _target_: resnet  # Auto-registers ResNet (matches class name)
  layers: 50
  pretrained: false
epochs: 100
```

This is useful with [`_ref_`](composition.md) composition - referenced files can specify their own `_target_` without pre-registration:

```yaml
# models/resnet.yaml (referenced via _ref_)
_target_: resnet
layers: 50
pretrained: false
```

#### When `_target_` is Required

- **Root config file** - Always required
- **Abstract base classes** - Cannot be instantiated directly
- **Base classes with multiple registered subclasses** - Ambiguous which to use
- **Union types** - Cannot determine which type to use

```python
from abc import ABC, abstractmethod

class BaseEncoder(ABC):
    @abstractmethod
    def encode(self): pass

class TransformerEncoder(BaseEncoder):
    def __init__(self, layers: int):
        self.layers = layers
    def encode(self): pass

class LSTMEncoder(BaseEncoder):
    def __init__(self, hidden_size: int):
        self.hidden_size = hidden_size
    def encode(self): pass

@dataclass
class Model:
    encoder: BaseEncoder  # Abstract - _target_ required!

rc.register(name="transformer", target=TransformerEncoder)
rc.register(name="lstm", target=LSTMEncoder)
rc.register(name="model", target=Model)
```

```yaml
_target_: model
encoder:
  _target_: transformer  # Required - BaseEncoder is abstract
  layers: 6
```

#### Auto-registration Requirements

- Parent field must have a type hint
- `_target_` name must match the type hint's class name (case-insensitive)
- The class must not be abstract
- The type hint must be a single class (not `Union[A, B]`)

**When auto-registration fails:**

- `TargetNotFoundError`: Target name doesn't match expected class
- `AmbiguousTargetError`: Type is abstract or has multiple implementations
