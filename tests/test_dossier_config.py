from workspace.dossier_config import (
    COMPANIES,
    CONFIDENCE_THRESHOLD,
    TAXONOMY,
)


def test_companies_have_real_identifiers():
    orti = COMPANIES["ORTI"]
    intur = COMPANIES["INTUR"]
    assert orti.tax_code == "04391390657"
    assert intur.tax_code == "00553430653"
    assert orti.drive_folder_id == "1jtik538_t4udzOM033KHXa88PaY-o53S"
    assert intur.drive_folder_id == "1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG"


def test_orti_never_searched_as_bare_word():
    orti = COMPANIES["ORTI"]
    for phrase in orti.search_phrases + orti.gmail_terms:
        assert phrase.strip().upper() != "ORTI", f"bare ORTI in {phrase!r}"


def test_taxonomy_shape():
    assert TAXONOMY[0] == "01_Societario"
    assert TAXONOMY[-1] == "_DaRivedere"
    assert len(TAXONOMY) == 9
    assert 0 < CONFIDENCE_THRESHOLD < 1
