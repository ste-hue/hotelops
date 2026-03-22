"""Pydantic schemas for HotelOps data contracts.

Every row going into BigQuery MUST pass through a schema model.
This prevents silent data corruption from format changes in source files.

Usage:
    from core.schemas import BudgetMensileRow, PianoFinanziarioInputRow, validate_batch
    validate_batch(rows, BudgetMensileRow, context="MAPPATURA costi fissi")
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# ── Shared types ─────────────────────────────────────────────────────────────

SocietaId = Literal["ORTI", "INTUR"]
BusinessUnitId = Literal["HOTEL", "RESIDENCE", "CVM", "LIDO", "HQ"]
TipoCosto = Literal["F", "V", "P", "X", "IP"]
Sezione = Literal["ENTRATE", "USCITE"]


# ── f_budget_mensile ─────────────────────────────────────────────────────────

class BudgetMensileRow(BaseModel):
    """Schema for f_budget_mensile rows."""
    societa_id: SocietaId
    anno: int
    mese: int
    codice_conto: str
    descrizione: Optional[str] = None
    tipo_costo: Optional[str] = None
    categoria_ce: Optional[str] = None
    business_unit_id: Optional[BusinessUnitId] = None
    importo: float
    fonte: str
    data_caricamento: str  # ISO timestamp

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("codice_conto")
    @classmethod
    def codice_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("codice_conto vuoto")
        return v.strip()


# ── f_piano_finanziario_input ────────────────────────────────────────────────

class PianoFinanziarioInputRow(BaseModel):
    """Schema for f_piano_finanziario_input rows."""
    hash_riga: str
    societa_id: SocietaId
    voce_id: str
    anno: int
    mese: int
    importo: Optional[float] = None
    fonte: str
    note: Optional[str] = None
    file_sorgente: Optional[str] = None
    data_caricamento: str  # ISO timestamp

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("voce_id")
    @classmethod
    def voce_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("voce_id vuoto")
        return v.strip()


# ── f_movimenti_contabili ────────────────────────────────────────────────────

class MovimentoContabileRow(BaseModel):
    """Schema for f_movimenti_contabili rows."""
    hash_riga: str
    societa_id: SocietaId
    cod_conto: str
    data_registrazione: date
    imp_dare: float
    imp_avere: float
    file_sorgente: str

    @field_validator("cod_conto")
    @classmethod
    def no_dots(cls, v: str) -> str:
        if "." in v:
            raise ValueError(f"cod_conto con punti: {v} — deve essere senza punti")
        return v


# ── f_banche_movimenti ───────────────────────────────────────────────────────

class BancaMovimentoRow(BaseModel):
    """Schema for f_banche_movimenti rows."""
    hash_riga: str
    societa_id: SocietaId
    banca_id: str
    data_operazione: date
    importo_netto: float
    descrizione: Optional[str] = None
    file_sorgente: str


# ── f_chiusura_mensile ────────────────────────────────────────────────────────

class ChiusuraMensileRow(BaseModel):
    """Schema for f_chiusura_mensile — monthly close snapshot.

    Saves the forecast vs actual delta at close time, so prediction
    accuracy can be tracked over time. Once written, never overwritten.
    """
    societa_id: SocietaId
    anno: int
    mese: int
    voce_id: str
    voce_label: str
    sezione: Sezione
    importo_consuntivo: float
    importo_previsione: float
    delta: float
    delta_pct: Optional[float] = None
    saldo_banca_fine_mese: Optional[float] = None
    data_chiusura: str  # ISO date when close was run

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v


# ── f_partite_aperte_fornitori ────────────────────────────────────────────────

class PartitaApertaFornitoreRow(BaseModel):
    """Schema for f_partite_aperte_fornitori — snapshot of open payables.

    Each row is an unpaid invoice/credit note from Esolver's
    "Situazione partite sintetica per fornitori".
    Pattern: DELETE-INSERT per societa_id + data_snapshot.
    """
    societa_id: SocietaId
    data_snapshot: date
    codice_fornitore: int
    nome_fornitore: str
    tipo_documento: str  # FT, NC, AFT
    numero_documento: str
    data_documento: date
    data_scadenza: date
    importo_residuo: float  # negative = we owe
    importo_abs: float  # always positive
    codice_pagamento: str  # 04=Bonifico, 03=SDD, 10=Carta, etc.
    metodo_pagamento: str  # Bonifico SEPA, SDD, Carta di credit, etc.
    is_intercompany: bool = False  # True if PANORAMA COMPANY / INTUR
    file_sorgente: str


# ── Validation helper ────────────────────────────────────────────────────────

class SchemaViolationError(Exception):
    """Raised when batch validation fails."""


def validate_batch(
    rows: list[dict],
    model: type[BaseModel],
    context: str,
    sample: int = 0,
) -> list[dict]:
    """Validate rows against a Pydantic model.

    Args:
        rows: List of dicts to validate.
        model: Pydantic model class.
        context: Human-readable label for error messages.
        sample: If > 0, only validate first N rows. 0 = validate all.

    Returns:
        The same rows list (pass-through for chaining).

    Raises:
        SchemaViolationError on first validation failure.
    """
    check = rows[:sample] if sample > 0 else rows
    for i, row in enumerate(check):
        try:
            model(**row)
        except Exception as e:
            raise SchemaViolationError(
                f"{context} riga {i}: {e}"
            ) from e
    return rows


def make_hash(*parts: str) -> str:
    """Create MD5 hash from pipe-separated parts."""
    key = "|".join(str(p) for p in parts)
    return hashlib.md5(key.encode()).hexdigest()
