"""Load the Home Assistant independent modules without importing the integration
package (whose __init__ needs Home Assistant itself)."""

import importlib
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "simson_pure"

if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "custom_components" / "simson")]
    sys.modules[PACKAGE] = package


def pure(name: str):
    return importlib.import_module(f"{PACKAGE}.{name}")
