import json

from app.tools import derivar_veterinario as mod


def test_derivar_veterinario_persiste_y_verifica_el_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DERIVACIONES_DIR", tmp_path)

    registro = mod.derivar_veterinario(motivo="Sospecha de problema renal", session_id="sesion-test")

    assert registro.session_id == "sesion-test"
    assert registro.motivo == "Sospecha de problema renal"
    assert registro.id.startswith("DER-")

    archivo = tmp_path / f"{registro.id}.json"
    assert archivo.exists()

    contenido = json.loads(archivo.read_text(encoding="utf-8"))
    assert contenido["id"] == registro.id
    assert contenido["session_id"] == "sesion-test"


def test_cada_derivacion_tiene_un_id_distinto(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DERIVACIONES_DIR", tmp_path)

    primera = mod.derivar_veterinario(motivo="motivo A", session_id="s1")
    segunda = mod.derivar_veterinario(motivo="motivo B", session_id="s2")

    assert primera.id != segunda.id
