from geoia.automation.engine import AutomationEngine


def test_boundary_valido():
    engine = AutomationEngine()
    coords = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    result = engine.validate_boundary(coords)
    assert result["is_valid"] is True
    assert result["area"] == 100.0
    assert result["perimeter"] == 40.0


def test_boundary_invalido_pocos_puntos():
    engine = AutomationEngine()
    result = engine.validate_boundary([(0, 0), (1, 0)])
    assert result["is_valid"] is False


def test_boundary_auto_interseccion_invalido():
    engine = AutomationEngine()
    coords = [(0, 0), (10, 0), (0, 10), (10, 10), (0, 0)]
    result = engine.validate_boundary(coords)
    assert result["is_valid"] is False
    assert "Self-intersection" in result["warnings"][0] or len(result["warnings"]) > 0
