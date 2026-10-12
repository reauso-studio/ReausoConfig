# ReausoConfig

A Python configuration library that turns YAML, JSON, and TOML files into Python objects with minimal runtime coupling.

## What is ReausoConfig?

ReausoConfig provides a simple way to load configuration files (YAML, JSON, or TOML) and instantiate Python objects from them. Unlike heavier frameworks, your application code doesn't need to know about ReausoConfig—only the startup/registration code does.

After instantiation, you get pure Python objects with no framework dependency.

## Key Features

- **Minimal coupling** — Your application code never imports rconfig; only startup code does
- **Object-oriented instantiation** — Config files describe object graphs, not just data
- **Multiple formats** — YAML, JSON, and TOML with automatic format detection
- **Config composition** — Split configs across files with `_ref_` references and deep merge
- **Type-driven resolution** — Automatic target inference from type hints
- **Interpolation** — `${...}` expressions with environment variables, math, and conditionals
- **Typed environment values** — String values from env vars are [converted](type-coercion.md) to the declared `bool`, `int`, enum, `list[str]`, ...
- **Lazy instantiation** — Defer object creation until first access
- **Provenance tracking** — Know where every config value came from
- **Config diffing** — Compare configurations programmatically
- **CLI overrides** — Override any config value from the command line (opt-in via `rc.set_cli_overrides(True)`)
- **Multirun support** — Generate config combinations for parameter sweeps
- **Lifecycle hooks** — React to config loading, instantiation, and errors

## Quick Example

```python
from dataclasses import dataclass
import rconfig as rc

# 1. Define your class (no framework dependency)
@dataclass
class ModelConfig:
    hidden_size: int
    dropout: float = 0.1

# 2. Register it
rc.register(name="model", target=ModelConfig)

# 3. Instantiate from config
model = rc.instantiate(path="config.yaml", expected_type=ModelConfig)
```

```yaml
# config.yaml
_target_: model
hidden_size: 256
dropout: 0.2
```

## Next Steps

- [Getting Started](getting-started.md) — Installation and a full walkthrough
- [Core Concepts](core-concepts.md) — Understand the fundamentals
- [Type Coercion](type-coercion.md) — How env and other string values become typed values
- [Embedding in Applications](embedding.md) — Using ReausoConfig in web apps, workers and tests
- [API Reference](api-reference.md) — Complete function and type reference
