# Getting Started

## What is ReausoConfig?

ReausoConfig provides a simple way to load configuration files (YAML, JSON, or TOML) and instantiate Python objects from them. Unlike heavier frameworks, your application code doesn't need to know about ReausoConfig—only the startup/registration code does.

After instantiation, you get pure Python objects with no framework dependency.

## Installation

Install ReausoConfig from PyPI:

```bash
pip install reausoconfig
```

!!! note "Package name vs. import name"
    The distribution is named `ReausoConfig`, the import name is `rconfig` (`import rconfig as rc`). `pip install rconfig` installs an unrelated package.

To install the latest development version from GitHub:

```bash
pip install git+https://github.com/reauso-studio/ReausoConfig.git
```

## Development Setup

For contributing or running tests, use pixi:

```bash
pixi install
pixi run test
```

## Quick Start

### 1. Define your classes

```python
from dataclasses import dataclass

@dataclass
class ModelConfig:
    hidden_size: int
    dropout: float = 0.1
```

### 2. Create a config file

**YAML** (config.yaml):

```yaml
_target_: model
hidden_size: 256
dropout: 0.2
```

**JSON** (config.json):

```json
{
    "_target_": "model",
    "hidden_size": 256,
    "dropout": 0.2
}
```

**TOML** (config.toml):

```toml
_target_ = "model"
hidden_size = 256
dropout = 0.2
```

The [`_target_`](core-concepts.md) key maps to a registered class name.

### 3. Register and instantiate

```python
import rconfig as rc

# Register your class
rc.register(name="model", target=ModelConfig)

# Instantiate the object (validates automatically)
# String paths work directly - no need for Path()
model = rc.instantiate(path="config.yaml", expected_type=ModelConfig)
print(model.hidden_size)  # 256
print(model.dropout)      # 0.2

# Optional: validate without instantiating (dry-run)
result = rc.validate(path="config.yaml")
if not result.valid:
    for error in result.errors:
        print(error)
```

## Command-Line Overrides

Reading `key=value` overrides and `--help` from `sys.argv` is off by default. Enable it at the start of a script:

```python
rc.set_cli_overrides(True)
model = rc.instantiate(path="config.yaml", expected_type=ModelConfig)
```

```bash
python train.py hidden_size=512   # Override a value
python train.py --help            # List all configurable values
```

See [CLI Overrides](composition.md#cli-overrides) for the full syntax.

## Supported File Formats

ReausoConfig has built-in support for three configuration formats:

| Format | Extensions          | Notes                                               |
| ------ | ------------------- | --------------------------------------------------- |
| YAML   | `.yaml`, `.yml` | Primary format, preserves comments with ruamel.yaml |
| JSON   | `.json`           | Standard JSON, good for programmatic generation     |
| TOML   | `.toml`           | Python 3.11+ (uses stdlib tomllib)                  |

The loader is selected automatically based on file extension:

```python
# All work the same way - string paths work directly
model = rc.instantiate(path="config.yaml")
model = rc.instantiate(path="config.json")
model = rc.instantiate(path="config.toml")

# Path objects also work
from pathlib import Path
model = rc.instantiate(path=Path("config.yaml"))
```

**Cross-format composition:** You can mix formats with [`_ref_`](composition.md):

```yaml
# trainer.yaml
_target_: trainer
model:
  _ref_: ./models/resnet.json  # Load JSON from YAML
settings:
  _ref_: ./settings.toml       # Load TOML from YAML
```
