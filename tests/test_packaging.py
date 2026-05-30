"""P00 packaging / migration smoke tests.

Guards the ``src/*`` -> ``src/torontosim/*`` restructure:
  * the ``torontosim`` package imports and exposes a version;
  * its subpackages import under the new namespace;
  * the legacy ``src.graph`` compatibility shims still resolve (until removed).
"""

from __future__ import annotations


def test_torontosim_imports_with_version():
    import torontosim

    assert isinstance(torontosim.__version__, str)
    assert torontosim.__version__


def test_subpackages_import_under_new_namespace():
    from torontosim.graph import routing  # noqa: F401
    from torontosim.model import predict_node_demand  # noqa: F401
    from torontosim.simulation import simulate_traffic  # noqa: F401


def test_legacy_shim_still_resolves():
    # train_*.sh and Liron's habits still use `from src.graph import ...`.
    from src.graph import routing as shim_routing
    from torontosim.graph import routing as real_routing

    # The shim re-points __path__ at the real package, so the same symbols
    # are reachable through both import paths.
    assert hasattr(shim_routing, "import_graph_json")
    assert hasattr(real_routing, "import_graph_json")
