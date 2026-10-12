# ReausoConfig

[![Tests](https://github.com/reauso-studio/ReausoConfig/actions/workflows/tests.yml/badge.svg)](https://github.com/reauso-studio/ReausoConfig/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-reauso--studio.github.io-blue)](https://reauso-studio.github.io/ReausoConfig/)

A Python configuration library that turns YAML, JSON, and TOML files into Python objects with minimal runtime coupling.

ReausoConfig loads configuration files and instantiates fully-connected object graphs by calling actual class constructors. Your application code doesn't need to know about ReausoConfig — only the startup/registration code does. After instantiation, you get pure Python objects with no framework dependency.

## Key Features

- **Minimal coupling** — Your application code never imports rconfig; only startup code does
- **Object-oriented instantiation** — Config files describe object graphs, not just data
- **Multiple formats** — YAML, JSON, and TOML with automatic format detection
- **Config composition** — Split configs across files with `_ref_` references and deep merge
- **Type-driven resolution** — Automatic target inference from type hints
- **Interpolation** — `${...}` expressions with environment variables, math, and conditionals
- **Typed environment values** — `"false"`, `"8080"` or `"a, b"` from env vars are converted to the field's declared `bool`, `int`, `list[str]`, enum, ...
- **Lazy instantiation** — Defer object creation until first access
- **Provenance tracking** — Know where every config value came from
- **Config diffing** — Compare configurations programmatically
- **CLI overrides** — Override any config value from the command line (opt-in)
- **Multirun support** — Generate config combinations for parameter sweeps
- **Lifecycle hooks** — React to config loading, instantiation, and errors

## Installation

```bash
pip install reausoconfig
```

The distribution is named `ReausoConfig`; the import name is `rconfig`. Note that `pip install rconfig` installs an unrelated package.

To install the latest development version from GitHub:

```bash
pip install git+https://github.com/reauso-studio/ReausoConfig.git
```

### Development Setup

```bash
pixi install
pixi run test
```

## Quick Start

### 1. Define your classes

Your classes have no dependency on ReausoConfig — use dataclasses, regular classes, or any callable:

```python
from dataclasses import dataclass

@dataclass
class Database:
    host: str
    port: int

@dataclass
class Service:
    name: str
    db: Database  # Nested object
```

### 2. Create a config file

The `_target_` key maps a config block to a registered class name. Nested blocks with `_target_` become nested object instances:

```yaml
# service.yaml
_target_: service
name: "api"
db:
  _target_: database
  host: "localhost"
  port: 5432
```

### 3. Register and instantiate

```python
import rconfig as rc

rc.register(name="database", target=Database)
rc.register(name="service", target=Service)

# One call creates the entire object graph
service = rc.instantiate(path="service.yaml")

assert isinstance(service, Service)
assert isinstance(service.db, Database)
assert service.db.host == "localhost"
```

The result is `Service(name="api", db=Database(host="localhost", port=5432))` — pure Python objects with no framework dependency.

## Config Composition

Split configuration across files and compose them with `_ref_`:

```yaml
# models/resnet.yaml
_target_: model
hidden_size: 256
dropout: 0.1
```

```yaml
# trainer.yaml
_target_: trainer
model:
  _ref_: models/resnet  # Load from file (format auto-detected)
  dropout: 0.2          # Override: merged on top
epochs: 10
```

Overrides are deep-merged — dict values merge recursively, scalars and lists are replaced.

## Supported Formats

ReausoConfig works with YAML, JSON, and TOML. The loader is selected automatically from the file extension:

```python
model = rc.instantiate(path="config.yaml")
model = rc.instantiate(path="config.json")
model = rc.instantiate(path="config.toml")
```

You can mix formats with `_ref_` — a YAML config can reference a JSON or TOML file and vice versa.

## Interpolation

Use `${...}` expressions for dynamic values:

```yaml
_target_: training
data_dir: '${env:DATA_DIR ?: "./data"}'   # Environment variable with default
batch_size: 32
total_samples: ${1000 * 32}               # Math expressions
output: ${data_dir}/results               # Reference other fields
use_gpu: '${env:USE_GPU ?: false}'        # Env strings are converted to the field type
device: '${/batch_size > 16 ? "cuda:0" : "cpu"}'  # Conditionals
```

## CLI Overrides

Override any config value from the command line without modifying files. CLI parsing is off by default (so `sys.argv` of a host application is never touched); enable it in scripts:

```python
rc.set_cli_overrides(True)  # or pass cli_overrides=True per call
service = rc.instantiate(path="service.yaml")
```

```bash
python main.py db.port=3306 name=prod
python main.py --help  # List all configurable values
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

@dataclass
class Trainer:
    optimizer: Optimizer  # Accepts any registered Optimizer subclass

rc.register(name="adam", target=Adam)
rc.register(name="trainer", target=Trainer)
```

```yaml
_target_: trainer
optimizer:
  _target_: adam  # Switch implementations by changing this value
  lr: 0.001
```

## Documentation

Full documentation is available at [reauso-studio.github.io/ReausoConfig](https://reauso-studio.github.io/ReausoConfig/), including:

- [Getting Started](https://reauso-studio.github.io/ReausoConfig/getting-started/) — Full installation and walkthrough
- [Core Concepts](https://reauso-studio.github.io/ReausoConfig/core-concepts/) — ConfigStore, validation, resolution pipeline
- [Config Composition](https://reauso-studio.github.io/ReausoConfig/composition/) — `_ref_`, `_instance_`, deep merge, CLI overrides
- [Type Coercion](https://reauso-studio.github.io/ReausoConfig/type-coercion/) — How string values (env vars) become typed values
- [Embedding in Applications](https://reauso-studio.github.io/ReausoConfig/embedding/) — Using ReausoConfig in web apps, workers and tests
- [API Reference](https://reauso-studio.github.io/ReausoConfig/api-reference/) — Complete function and type reference

## License

MIT License — see [LICENSE](LICENSE) for details.
