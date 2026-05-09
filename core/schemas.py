"""Pydantic schemas for HotelOps data contracts.

Every row going into BigQuery MUST pass through a schema model.
This prevents silent data corruption from format changes in source files.

Usage:
    from core.schemas import BudgetMensileRow, PianoFinanziarioInputRow, validate_batch
    validate_batch(rows, BudgetMensileRow, context="MAPPATURA costi fissi")
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


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
    # Additional BQ columns (NULLABLE — populated by parsers when available).
    id_documento: Optional[int] = None
    num_progr_riga: Optional[int] = None
    gruppo_doc: Optional[str] = None
    anno: Optional[int] = None
    mese: Optional[int] = None
    sigla_doc: Optional[str] = None
    rif_registrazione: Optional[str] = None
    num_doc_originale: Optional[str] = None
    data_originale: Optional[str] = None  # ISO date
    tipo_documento: Optional[str] = None
    cod_partitario: Optional[str] = None
    rag_sociale: Optional[str] = None
    causale_contabile: Optional[str] = None
    cod_divisione: Optional[str] = None
    data_ingresso: Optional[str] = None  # ISO date
    raw_object_id: Optional[str] = None

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
    # 5D dimensions (societa_id required above; others optional per data model).
    business_unit_id: Optional[BusinessUnitId] = None
    funzione_id: Optional[str] = None
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    # Additional BQ columns (NULLABLE — populated by parsers when available).
    id_movimento: Optional[str] = None
    data_valuta: Optional[str] = None  # ISO date
    divisa: Optional[str] = None
    importo_debito: Optional[float] = None
    importo_credito: Optional[float] = None
    categoria_raw: Optional[str] = None
    sottocategoria_raw: Optional[str] = None
    categoria_normalizzata: Optional[str] = None
    sottocategoria_normalizzata: Optional[str] = None
    tipo_movimento: Optional[str] = None
    codice_identificativo_banca: Optional[str] = None
    etichette: Optional[str] = None
    note: Optional[str] = None
    data_ingresso: Optional[str] = None  # ISO date
    riga_sorgente: Optional[int] = None
    # FK to f_raw_objects.raw_object_id (Phase 4 FK — pilot on banca).
    raw_object_id: Optional[str] = None


# ── f_saldi_banca_snapshot ───────────────────────────────────────────────────


class SaldoBancaSnapshotRow(BaseModel):
    """Schema for f_saldi_banca_snapshot — daily running balance per banca.

    Sourced from Esolver scheda contabile (running saldo for the fiscal year,
    not absolute bank balance). One row per (societa, banca, day).
    """

    societa_id: SocietaId
    banca_id: str
    data_snapshot: date
    saldo_finale: float


# ── f_saldi_banca_chiusura_mensile ────────────────────────────────────────────


class SaldoBancaChiusuraMensileRow(BaseModel):
    """Saldo banca certificato a fine mese (fonte manuale / tesoreria).

    Se presente per (societa_id, data_riferimento, banca_id), ha priorità su
    snapshot Esolver + movimenti in ``hotelops chiudi`` e nel calcolo saldi CLI.
    """

    societa_id: SocietaId
    data_riferimento: date
    banca_id: str
    saldo_eur: float
    note: Optional[str] = None


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


# ── f_vendite_fb ──────────────────────────────────────────────────────────────


class VenditaFbRow(BaseModel):
    """Schema for f_vendite_fb — POS F&B sales at article × day × sala level.

    Source: HotelCube/POS export (XLSX), columns Sala/Cod Articolo/Tipo Piatto/
    Qtà/Importo/Sconto/Netto. Granularità giorno × sala × articolo.

    Pattern: APPEND + hash_riga dedup. Idempotent re-ingest of same export
    via filter_new_rows_by_hash.

    Lato ricavo del food cost. Si incrocia con f_consumi_economato (lato
    costo) tramite mese × sala/reparto o mese × tipo_piatto/categoria.
    """

    hash_riga: str
    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    anno: int
    mese: int
    data_servizio: date
    sala: str  # BAR / RISTO_LUNCH / RISTO_DINNER (normalizzato)
    codice_articolo: str
    descrizione: str
    tipo_piatto: str  # BIRRE, COCKTAIL, VINI, CAFFETTERIA, ...
    sub_tipo_piatto: Optional[str] = None
    quantita: float
    importo_lordo: float
    sconto: Optional[float] = None
    importo_netto: float  # ← metric for food cost ratio
    segmento_cliente: Optional[str] = None  # da Ristocube: ZRISTINT/ZRISTEST/INLE/...
    file_sorgente: str
    data_caricamento: datetime

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v


# ── f_ricavi_storici ─────────────────────────────────────────────────────────


class RicaviStoriciRow(BaseModel):
    """Schema for f_ricavi_storici — historical revenue by BU and month.

    Source: Riepilogo Entrate XLSX from Antonio (2023-2025).
    Pattern: APPEND + hash_riga dedup.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    anno: int
    mese: int
    importo_entrate: float
    fonte: str
    hash_riga: str
    data_caricamento: str  # ISO timestamp

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v


# ── d_coefficienti_stagionalita ──────────────────────────────────────────────


class CoefficienteStagionalitaRow(BaseModel):
    """Schema for d_coefficienti_stagionalita — monthly seasonality weights.

    coefficiente = 1.0 means average month. >1 = above-average, <1 = below.
    Sum of 12 months' coefficients per BU = 12.0.
    Source: computed from f_ricavi_storici (2023-2025 weighted average).
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    mese: int
    coefficiente: float
    fonte: str
    hash_riga: str
    data_caricamento: str

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("coefficiente")
    @classmethod
    def coeff_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"coefficiente negativo: {v}")
        return v


# ── d_anagrafica_fornitori ──────────────────────────────────────────────────


class AnagraficaFornitoreRow(BaseModel):
    """Schema for d_anagrafica_fornitori — Esolver supplier master data.

    Source of truth for supplier identity. Loaded from Esolver anagrafica export.
    Pattern: WRITE_TRUNCATE (full reload).
    """

    codice_fornitore: int
    ragione_sociale: str
    partita_iva: Optional[str] = None
    codice_fiscale: Optional[str] = None
    comune: Optional[str] = None
    provincia: Optional[str] = None
    tipo_soggetto: Optional[str] = None
    stato_anagrafica: Optional[str] = None
    data_caricamento: str  # ISO timestamp


# ── d_mapping_piano_finanziario ────────────────────────────────────────────

TipoMapping = Literal["FORNITORE", "CATEGORIA"]


class MappingPianoFinanziarioRow(BaseModel):
    """Schema for d_mapping_piano_finanziario — maps PF sub-items to Esolver codes.

    Each row connects a sotto-voce in Rosa's PF Excel to either:
    - FORNITORE: a specific supplier (codice_fornitore FK → d_anagrafica_fornitori)
    - CATEGORIA: an Esolver account code pattern (cod_conto_pattern)

    Per-società: ORTI and INTUR have different suppliers and sub-items.
    Pattern: WRITE_TRUNCATE (full reload from CSV).
    """

    societa_id: SocietaId
    voce_id: str
    sotto_voce: str
    tipo: TipoMapping
    codice_fornitore: Optional[int] = None
    cod_conto_pattern: Optional[str] = None
    nome_esolver: Optional[str] = None

    @field_validator("codice_fornitore")
    @classmethod
    def fornitore_required_if_type(cls, v, info):
        if info.data.get("tipo") == "FORNITORE" and v is None:
            raise ValueError("codice_fornitore required when tipo=FORNITORE")
        return v


# ── Validation helper ────────────────────────────────────────────────────────


class SchemaViolationError(Exception):
    """Raised when batch validation fails."""


class PmsStatisticheRow(BaseModel):
    """Schema for f_pms_statistiche — PMS daily room/occupancy/revenue statistics.

    Source: HotelCube PMS Dashboard Manager (daily export per BU).
    Daily granularity. BU detected from Camere Totali signature.
    """

    societa_id: SocietaId
    business_unit_id: str
    data: str  # YYYY-MM-DD
    camere_totali: int
    camere_vendute: int
    camere_bloccate: int
    occupazione_pct: float  # 0-100
    pax_in_casa: int
    adr: float  # Average Daily Rate
    revpar: float  # Revenue Per Available Room
    revenue_room: float
    revenue_fb: float
    revenue_parking: float
    revenue_totale: float
    fonte: str
    hash_riga: str
    data_caricamento: str

    @field_validator("occupazione_pct")
    @classmethod
    def _occ_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError(f"occupazione fuori range: {v}")
        return v


class CoefficienteConsumoRow(BaseModel):
    """Schema for f_coefficienti_consumo — consumption coefficients per product/dept/month.

    Source: Consumption Coefficients 2025.xlsx (from economato data + pernottamenti).
    One row per product × department × month.
    """

    societa_id: SocietaId
    anno: int
    mese: int
    reparto: str
    descrizione_articolo: str
    categoria: str
    classe: str
    quantita: float
    unita_misura: str
    pernottamenti: int
    coeff_per_pax: float
    costo_per_pax: float
    importo: float
    hash_riga: str
    data_caricamento: str

    @field_validator("mese")
    @classmethod
    def _mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v


# ── f_reviews ───────────────────────────────────────────────────────────────

PiattaformaReview = Literal["BOOKING", "TRIPADVISOR", "GOOGLE", "EXPEDIA", "TRIP"]
CategoriaNlp = Literal[
    "PULIZIA",
    "CIBO",
    "STAFF",
    "STRUTTURA",
    "POSIZIONE",
    "RUMORE",
    "PREZZO",
    "WIFI",
    "GENERICA",
]
SentimentNlp = Literal["POSITIVO", "NEGATIVO", "MISTO"]
TipoViaggio = Literal["COPPIA", "FAMIGLIA", "BUSINESS", "SOLO", "AMICI"]


class ReviewRow(BaseModel):
    """Schema for f_reviews — guest reviews from OTA platforms.

    Source: Apify scrapers (Booking, TripAdvisor, Google, Expedia).
    Pattern: APPEND + review_hash dedup.
    """

    review_hash: str
    piattaforma: PiattaformaReview
    review_id: str
    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    punteggio_raw: float
    punteggio_norm: float
    testo: str
    testo_positivo: Optional[str] = None
    testo_negativo: Optional[str] = None
    titolo: Optional[str] = None
    lingua: str
    data_review: str  # ISO date
    data_soggiorno: Optional[str] = None  # ISO date
    reviewer_nome: Optional[str] = None
    reviewer_paese: Optional[str] = None
    tipo_viaggio: Optional[TipoViaggio] = None
    camera_tipo: Optional[str] = None
    url_review: Optional[str] = None
    categoria_nlp: Optional[CategoriaNlp] = None
    sentiment_nlp: Optional[SentimentNlp] = None
    riassunto_nlp: Optional[str] = None
    alert_inviato: bool = False
    data_ingest: str  # ISO timestamp

    @field_validator("review_hash")
    @classmethod
    def hash_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("review_hash vuoto")
        return v.strip()

    @field_validator("testo")
    @classmethod
    def testo_strip(cls, v: str) -> str:
        # Empty text is allowed: Google and Booking permit star-only reviews.
        # A 1-star review without comment is still a valid alert signal.
        return (v or "").strip()

    @field_validator("punteggio_norm")
    @classmethod
    def norm_range(cls, v: float) -> float:
        if not 1.0 <= v <= 10.0:
            raise ValueError(f"punteggio_norm fuori range 1-10: {v}")
        return v


# ── f_apify_runs ─────────────────────────────────────────────────────────────


class ApifyRunRow(BaseModel):
    """Schema for f_apify_runs — one row per Apify actor run (cost observability).

    Source: reviews/scrape.py after each client.actor().call().
    Pattern: APPEND (no dedup — run_id is unique per Apify invocation).
    """

    run_id: str
    piattaforma: PiattaformaReview
    business_unit_id: BusinessUnitId
    actor_id: str
    ts_run: str  # ISO timestamp
    n_items: int
    cost_usd: Optional[float] = None  # None when Apify doesn't return usageTotalUsd
    cap_violated: bool = False

    @field_validator("run_id")
    @classmethod
    def run_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("run_id vuoto")
        return v.strip()

    @field_validator("n_items")
    @classmethod
    def n_items_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"n_items negativo: {v}")
        return v


# ── f_coperti_giornalieri ────────────────────────────────────────────────────


class CopertoGiornalieroRow(BaseModel):
    """Schema for f_coperti_giornalieri.

    natural_key for SNAPSHOT writes is hash_riga (computed from societa,
    data_servizio, tipo_pasto, tipo_ospite, business_unit_id by the
    pipeline). Stored as a column rather than reconstructed at write time
    so back-fill / debug is possible.
    """

    societa_id: SocietaId
    anno: int
    mese: int
    data_servizio: date
    tipo_pasto: str
    tipo_ospite: str
    business_unit_id: str | None = None
    n_coperti: int
    fonte: str | None = None
    hash_riga: str
    data_caricamento: datetime


# ── f_pipeline_runs ──────────────────────────────────────────────────────────


class PipelineRunRow(BaseModel):
    """Schema for f_pipeline_runs — one row per pipeline execution.

    Layer 2 observability: answers "did the cron run?", "did it succeed?",
    "is any pipeline silently dead?". Complementary to f_apify_runs
    (one row per actor.call() — cost observability).
    """

    run_id: str
    pipeline_name: str
    started_at: str  # ISO timestamp
    ended_at: Optional[str] = None
    status: Literal["OK", "FAIL", "PARTIAL"]
    societa_id: Optional[SocietaId] = None
    rows_found: Optional[int] = None
    rows_new: Optional[int] = None
    alerts_sent: Optional[int] = None
    usage_total_usd: Optional[float] = None
    error_message: Optional[str] = None
    meta_json: Optional[str] = None


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
            raise SchemaViolationError(f"{context} riga {i}: {e}") from e
    return rows


def make_hash(*parts: str) -> str:
    """Create MD5 hash from pipe-separated parts."""
    key = "|".join(str(p) for p in parts)
    return hashlib.md5(key.encode()).hexdigest()
