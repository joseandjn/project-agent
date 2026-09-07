from app.tools import scoring as mod


def test_calcular_confianza_feedback_vacio_retorna_diccionario_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "FEEDBACK_PATH", tmp_path / "feedback.json")
    assert mod.calcular_confianza_feedback() == {}


def test_registrar_feedback_aplica_laplace_sin_historial(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "FEEDBACK_PATH", tmp_path / "feedback.json")

    mod.registrar_feedback("SKU-1", acierto=True)
    mod.registrar_feedback("SKU-1", acierto=True)
    mod.registrar_feedback("SKU-2", acierto=False)

    confianza = mod.calcular_confianza_feedback()

    # SKU-1: (2 aciertos + 1) / (2 + 0 + 2) = 0.75
    assert confianza["SKU-1"] == 0.75
    # SKU-2: (0 aciertos + 1) / (0 + 1 + 2) = 0.3333...
    assert round(confianza["SKU-2"], 4) == 0.3333
    # sin historial, un SKU nunca registrado no aparece; el caller debe usar .get(sku, 0.5)
    assert "SKU-3" not in confianza
