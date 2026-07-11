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

OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)
"""Switch operativo HotelCube INTUR → ORTI.

Pre 2025-04-01: INTUR gestiva Hotel+Residence+CVM. Post: ORTI gestisce le
operations. Deriva societa_id da date HotelCube (produzione, accodamenti, ...).
"""


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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
    raw_object_id: Optional[str] = None

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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
    raw_object_id: Optional[str] = None

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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
    raw_object_id: Optional[str] = None


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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
    raw_object_id: Optional[str] = None


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


# ── f_ricavi_fb ──────────────────────────────────────────────────────────────


class RicaviFbRow(BaseModel):
    """Schema for f_ricavi_fb — F&B revenue by structure × month × charge code.

    Source: HotelCube Power BI "Produzione Netta Dashboard" XLSX, one file per
    struttura × mese. Drill-down of classe 02FB into ~20 charge codes
    (SCBKFBB, RISLFOOD, DINFOOD, ...).

    Pattern: SNAPSHOT, natural_key (business_unit_id, anno, mese). Re-loading a
    month replaces that structure-month's rows.

    Lato ricavo del food cost. Si incrocia con f_consumi_economato (costo,
    globale) tramite mese, e con f_coperti_giornalieri (pasti) tramite mese × BU.

    `raw_object_id` is the FK to `f_raw_objects` stamped by the `promote` path.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    anno: int
    mese: int
    codice: str
    descrizione: Optional[str] = None
    netto: float
    lordo: float
    file_sorgente: str
    hash_riga: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("codice")
    @classmethod
    def codice_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("codice vuoto")
        return v


class ProduzioneRow(BaseModel):
    """Schema for f_produzione_pms — daily production by struttura × classe.

    Source: HotelCube Power BI Daily Production Report (taglio classe, Imponibile),
    one file per struttura × anno. Grana giorno × struttura × classe.

    Pattern: SNAPSHOT, natural_key (business_unit_id, anno). Re-export di una
    struttura×anno rimpiazza quelle righe (robusto agli storni).

    societa_id derivata da `data` vs OPERATIONS_CUTOVER_DATE.
    raw_object_id = FK a f_raw_objects, stampato dal path `promote`.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    data: date
    anno: int
    mese: int
    classe: str
    importo_imponibile: Decimal
    file_sorgente: str
    hash_riga: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime

    @field_validator("classe")
    @classmethod
    def classe_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("classe vuoto")
        return v

    @model_validator(mode="after")
    def societa_matches_cutover(self) -> "ProduzioneRow":
        expected = "INTUR" if self.data < OPERATIONS_CUTOVER_DATE else "ORTI"
        if self.societa_id != expected:
            raise ValueError(
                f"societa_id={self.societa_id!r} incoerente con cutover "
                f"{OPERATIONS_CUTOVER_DATE} per data {self.data}"
            )
        return self

    @model_validator(mode="after")
    def anno_mese_match_data(self) -> "ProduzioneRow":
        if self.data.year != self.anno or self.data.month != self.mese:
            raise ValueError(
                f"anno/mese ({self.anno}/{self.mese}) incoerenti con data {self.data}"
            )
        return self


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


# ── d_fornitori ─────────────────────────────────────────────────────────────


class FornitoreMapRow(BaseModel):
    """Riga di d_fornitori — mappa fornitore → voce PF + flag esclusione."""

    codice_fornitore: int
    nome_esolver: str
    nome_pf: str = ""
    voce_id: str = ""
    is_intercompany: bool = False
    is_excluded: bool = False
    exclude_reason: str = ""
    societa_id: str  # ORTI | INTUR


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


# ── d_camere ─────────────────────────────────────────────────────────────────


class CameraRow(BaseModel):
    """Schema for d_camere — physical room inventory (Hotel Panorama).

    Static hand-curated dimension (source: sheet "Distribuzione camere",
    86 rooms). Denominator for occupancy/booking pace once f_prenotazioni_otb
    lands. Pattern: WRITE_TRUNCATE (full reload from CSV).
    """

    room_id: str
    piano: int
    cod_camera: Optional[str] = None
    tipologia: str
    occupazione: Optional[str] = None
    pax_max: Optional[int] = Field(default=None, ge=1, le=6)
    vista: Optional[str] = None
    esposizione: Optional[str] = None
    affaccio: Optional[str] = None
    doccia_vasca: Optional[str] = None
    letto_principale: Optional[str] = None
    letto_secondario: Optional[str] = None
    bagno_fa: Optional[Literal["F", "A"]] = None
    comunicante_con: Optional[str] = None
    note: Optional[str] = None
    business_unit_id: BusinessUnitId
    societa_id: SocietaId

    @field_validator("room_id", "tipologia")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v


# ── d_pms_codici ─────────────────────────────────────────────────────────────

DominioPmsCodice = Literal[
    "TRATTAMENTO",
    "CANALE",
    "NAZIONE",
    "SEGMENTO",
    "TIPO_DITTA",
    "ROOM_TYPE",
    "CLASSE_TARIFFA",
]


class PmsCodiceRow(BaseModel):
    """Schema for d_pms_codici — code→description lookups from HotelCube/Power BI.

    One table, 7 domains (legende prenotazioni: trattamenti, canali, nazioni,
    segmenti, tipi ditta, room types, classi tariffe). Static hand-curated
    dimension. Pattern: WRITE_TRUNCATE (full reload from CSV).
    """

    dominio: DominioPmsCodice
    codice: str
    descrizione: str

    @field_validator("codice")
    @classmethod
    def codice_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("codice vuoto")
        return v


# ── f_pec_messages / f_pec_allegati ──────────────────────────────────────────

SourceFolderPec = Literal["RECEIVED", "SENT"]
TipoPec = Literal[
    "POSTA_CERTIFICATA",
    "ACCETTAZIONE",
    "CONSEGNA",
    "ANOMALIA",
    "MESSAGGIO_INVIATO",
    "ALTRO",
]


class PecMessageRow(BaseModel):
    """Schema for f_pec_messages — una riga per busta PEC ricevuta o messaggio inviato.

    Le ricevute (ACCETTAZIONE/CONSEGNA) sono righe autonome: fatti immutabili,
    linkate al messaggio originale via ref_msgid. source_folder è il fatto
    osservato (derivato dall'anatomia: busta ⇒ RECEIVED, raw ⇒ SENT); ogni
    semantica derivata vive in v_pec_conversazioni. Fatti documentali, non
    finanziari: I4 non applicabile. Lifecycle: APPEND, dedup su hash_riga=md5(msgid).
    """

    msgid: str
    source_folder: SourceFolderPec
    tipo: TipoPec
    ref_msgid: Optional[str] = None
    data_evento: datetime
    data_certificata: bool
    mittente: Optional[str] = None
    destinatari: Optional[str] = None  # ";"-joined
    n_destinatari: int = 0
    subject: Optional[str] = None
    body_text: Optional[str] = None
    provider: Optional[str] = None  # dominio busta — solo RECEIVED
    casella: str
    societa_id: SocietaId
    n_allegati: int = 0
    ha_postacert: bool = False
    parse_warning: Optional[str] = None
    hash_riga: str
    raw_object_id: str
    data_caricamento: datetime

    @field_validator("msgid", "casella", "hash_riga", "raw_object_id")
    @classmethod
    def pec_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v


class PecAllegatoRow(BaseModel):
    """Schema for f_pec_allegati — un allegato reale trasmesso in una PEC.

    Esclusi gli artefatti di busta (daticert.xml, smime.p7s, postacert.eml).
    Il binario vive su GCS content-addressed; gcs_uri è NULL solo se
    l'estrazione è fallita (parse_warning sul messaggio). APPEND, dedup su
    hash_riga=md5(msgid|sha256|nome_file).
    """

    msgid: str
    nome_file: str
    mime_type: Optional[str] = None
    size_bytes: int = 0
    sha256: str
    is_firmato: bool = False
    gcs_uri: Optional[str] = None
    hash_riga: str
    raw_object_id: str
    data_caricamento: datetime

    @field_validator("msgid", "nome_file", "sha256", "hash_riga", "raw_object_id")
    @classmethod
    def pec_all_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
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
    raw_object_id: Optional[str] = None

    @field_validator("occupazione_pct")
    @classmethod
    def _occ_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError(f"occupazione fuori range: {v}")
        return v


class PrenotazioniOtbRow(BaseModel):
    """Schema for f_prenotazioni_otb — portafoglio prenotazioni on-the-books.

    Source: Power BI "Andamento Prenotazioni" (POWERBI_ANDAMENTOPRENOTAZIONI).
    Ogni export = una FOTOGRAFIA del portafoglio (consumato + futuro) alla
    snapshot_date; le fotografie si accumulano (booking pace), la SNAPSHOT
    delete è scoped a (snapshot_date, business_unit_id, dim_tipologia).
    dim_tipologia distingue le varianti del report: ASSEGNATA (camera
    assegnata), VENDUTA (camera pagata), NESSUNA (export senza tipologia).
    Mai sommare varianti diverse della stessa snapshot_date: sono la stessa
    fotografia aggregata su dimensioni diverse.
    """

    snapshot_date: str  # YYYY-MM-DD (data intake del raw object)
    societa_id: SocietaId
    business_unit_id: str
    data: str  # YYYY-MM-DD, data soggiorno
    dim_tipologia: Literal["ASSEGNATA", "VENDUTA", "NESSUNA"]
    tipologia: Optional[str] = None
    camere: int
    presenze_arb: int
    importo_lordo: float
    adr_lordo: float
    imponibile: float
    adr_imponibile: float
    fonte: str
    hash_riga: str
    data_caricamento: str
    raw_object_id: Optional[str] = None


class BookingsTipologiaRow(BaseModel):
    """Schema for f_bookings_tipologia — venduto giornaliero per tipologia venduta.

    Source: Power BI "Detailed Data for Bookings" (POWERBI_BOOKINGSTIPOLOGIA).
    Consuntivo (fotografia rivedibile) → SNAPSHOT replace per
    (business_unit_id, data). Imponibile; codici tipologia decodificati da
    d_pms_codici (dominio ROOM_TYPE).
    """

    societa_id: SocietaId
    business_unit_id: str
    data: str  # YYYY-MM-DD
    tipologia: str
    camere: int
    pax_arb: int
    infant: int
    adr: float
    ricavo_camera: float
    ricavo_camera_extra: float
    ricavo_extra: float
    ricavo_totale: float
    fonte: str
    hash_riga: str
    data_caricamento: str
    raw_object_id: Optional[str] = None


class ConsprevMensileRow(BaseModel):
    """Schema for f_consprev_mensile — rollup mensile forecast PMS.

    Source: Power BI "Consuntivo + Previsione" (POWERBI_CONSPREV).
    Per (mese × classe × categoria × addebito): consumato, consumato +
    portafoglio prenotazioni, budget PMS, anno precedente. Ogni export è
    una FOTOGRAFIA alla snapshot_date (le fotografie si accumulano);
    SNAPSHOT delete scoped a (snapshot_date, business_unit_id).
    """

    snapshot_date: str  # YYYY-MM-DD (data intake del raw object)
    societa_id: SocietaId
    business_unit_id: str
    anno: int
    mese: int  # 1-12
    classe: str
    categoria: Optional[str] = None
    addebito: Optional[str] = None
    mese_cons: float
    mese_prev_cons: float
    mese_bdg: float
    mese_ap: float
    fonte: str
    hash_riga: str
    data_caricamento: str
    raw_object_id: Optional[str] = None


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

    Source: verticals/reviews/scrape.py after each client.actor().call().
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
    # FK to f_raw_objects.raw_object_id (Phase 4 FK).
    raw_object_id: Optional[str] = None


# ── projects (event-sourced Step 1) ──────────────────────────────────────────


class Rata(BaseModel):
    """Una rata di pagamento dentro un piano (ImpegnoMeta.rate[])."""

    seq: int
    data_prevista: date
    importo_eur: Decimal
    descrizione: str
    stato: Literal["PIANIFICATA", "EMESSA", "PAGATA", "ANNULLATA"]


class PreventivoMeta(BaseModel):
    """metadata per evento tipo_evento='PREVENTIVO'."""

    tipo: Literal["PREVENTIVO"] = "PREVENTIVO"
    numero_preventivo: Optional[str] = None
    data_preventivo: Optional[date] = None
    validita_fino_a: Optional[date] = None
    articolo: str
    codice_articolo: Optional[str] = None
    stato_preventivo: Literal["RICEVUTO", "ACCETTATO", "RIFIUTATO", "SCADUTO"]
    note: Optional[str] = None


class ImpegnoMeta(BaseModel):
    """Metadata per evento tipo_evento='IMPEGNO' (commitment firmato)."""

    tipo: Literal["IMPEGNO"] = "IMPEGNO"
    from_preventivo_evento_id: Optional[str] = None
    numero_contratto: Optional[str] = None
    data_firma: date
    rate: list[Rata]
    stato_commitment: Literal["FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    motivo_variazione: Optional[str] = None  # popolato solo per impegni successivi


class FatturaMeta(BaseModel):
    """Metadata per evento tipo_evento='FATTURA'."""

    tipo: Literal["FATTURA"] = "FATTURA"
    numero_fattura: str
    data_emissione: date
    data_ricezione: Optional[date] = None
    tipo_doc: Literal["FT", "FT-RC", "NC"]
    condizioni_pagamento: str
    data_scadenza: Optional[date] = None
    movimento_row_hash: Optional[str] = None  # FK a f_movimenti_contabili
    copre_rate: list[int] = []  # seq rate IMPEGNO che questa fattura sta fatturando


class PagamentoMeta(BaseModel):
    """Metadata per evento tipo_evento='PAGAMENTO'."""

    tipo: Literal["PAGAMENTO"] = "PAGAMENTO"
    data_valuta: date
    metodo: Literal["BONIFICO", "SDD", "RID", "ASSEGNO", "CASSA"]
    importo_pagato_eur: Decimal
    copre_fatture: list[str]  # evento_id FATTURA coperti
    banca_movimento_hash: Optional[str] = None  # FK a f_banche_movimenti


class DocumentoMeta(BaseModel):
    """Metadata per evento tipo_evento='DOCUMENTO' (allegato Drive)."""

    tipo: Literal["DOCUMENTO"] = "DOCUMENTO"
    tipo_doc: Literal[
        "PREVENTIVO",
        "CONTRATTO",
        "ORDINE",
        "FATTURA",
        "SAL",
        "PLANIMETRIA",
        "EMAIL",
        "ALTRO",
    ]
    drive_url: str
    file_name: str
    file_hash_md5: str  # dedup
    correlato_evento_id: Optional[str] = None


class Progetto(BaseModel):
    """Anagrafica progetto. Lifecycle: SNAPSHOT per progetto_id."""

    progetto_id: str  # HPAN25PIANO1, SPIAGGIA_LOTTO7
    nome: str
    societa_owner_id: SocietaId  # ORTI o INTUR (riusato da type alias esistente)
    business_unit_id: BusinessUnitId  # HOTEL/RESIDENCE/CVM/LIDO/HQ (riusato)
    struttura: Optional[str] = None
    budget_cap_eur: Decimal
    data_inizio: date
    data_fine_prevista: Optional[date] = None
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str
    drive_root_url: Optional[str] = None


class ProgettoVoce(BaseModel):
    """Identità di una riga di scope. Lifecycle: SNAPSHOT per voce_id."""

    voce_id: str  # composito {progetto_id}.{seq}
    progetto_id: str
    codice_interno: str  # "001", "002"
    descrizione: str
    categoria: str  # stringa libera: EDILE, IMPIANTI_EL, OMBRELLONI, ...
    qta: Optional[Decimal] = None
    unita: Optional[str] = None  # pz, mq, cad, set
    fornitore_id: Optional[str] = (
        None  # FK d_anagrafica_fornitori, popolato alla SCELTA
    )
    societa_pagante_id: SocietaId  # default INTUR, ORTI per opex
    note: Optional[str] = None


# Type alias for discriminated metadata (Pydantic v2 union with discriminator on `tipo` field)
ProgettoEventoMetadata = Annotated[
    Union[
        PreventivoMeta,
        ImpegnoMeta,
        FatturaMeta,
        PagamentoMeta,
        DocumentoMeta,
    ],
    Field(discriminator="tipo"),
]


class ProgettoEvento(BaseModel):
    """Evento immutabile sul thread di una voce. Lifecycle: APPEND."""

    evento_id: str  # UUID
    voce_id: str  # FK ProgettoVoce
    progetto_id: str  # denormalized for query speed
    tipo_evento: Literal["PREVENTIVO", "IMPEGNO", "FATTURA", "PAGAMENTO", "DOCUMENTO"]
    data_evento: date
    data_registrazione: str  # ISO datetime
    importo_eur: Optional[Decimal] = None
    fornitore_id: Optional[str] = None
    metadata: ProgettoEventoMetadata
    file_sorgente: Optional[str] = None  # drive_url del file che ha generato l'evento

    @model_validator(mode="after")
    def tipo_consistency(self) -> ProgettoEvento:
        """metadata.tipo deve combaciare con tipo_evento (I1)."""
        if self.metadata.tipo != self.tipo_evento:
            raise ValueError(
                f"tipo_evento={self.tipo_evento!r} but metadata.tipo={self.metadata.tipo!r}"
            )
        return self


# ── f_ristocube_orders ────────────────────────────────────────────────────────


class RistocubeOrderRow(BaseModel):
    """Schema for f_ristocube_orders — comande RistoCube at item × comanda level.

    Source: "Orders Report RISTOCUBE*.xlsx" — one file per export period.
    Pattern: APPEND + hash_riga dedup.

    Granularità: una riga per item × comanda. I campi della comanda (tavolo,
    sala, coperti, segmento, etc.) sono ereditati da ogni item.

    `raw_object_id` is the FK to `f_raw_objects` stamped by the `promote` path.
    """

    hash_riga: str
    societa_id: SocietaId
    business_unit_id: str
    data: date
    anno: int
    mese: int
    giorno: int
    orario_apertura: Optional[str] = None
    orario_chiusura: Optional[str] = None
    tavolo: Optional[str] = None
    sala: str
    comanda_id: int
    coperti_comanda: Optional[int] = None
    totale_comanda: Optional[float] = None
    operatore_apertura: Optional[str] = None
    modalita_chiusura: Optional[str] = None
    segmento_cliente: Optional[str] = None
    importo_pagamento: Optional[float] = None
    mp: Optional[str] = None
    note_direzione: Optional[str] = None
    item_menu: Optional[str] = None
    item_codice_pos: str
    item_descrizione: Optional[str] = None
    item_quantita: Optional[float] = None
    item_importo_originale: Optional[float] = None
    item_sconto_tipo: Optional[str] = None
    item_importo_sconto: Optional[float] = None
    item_importo_finale: Optional[float] = None
    file_sorgente: Optional[str] = None
    raw_object_id: Optional[str] = None
    data_caricamento: datetime


# ── f_spiaggia_* ─────────────────────────────────────────────────────────────

# Type alias: needed because SpiaggiaCashFlowRow has a field named `date` which
# would shadow the built-in `date` type within Pydantic v2 class body resolution.
_Date = date


class SpiaggiaReservationRow(BaseModel):
    """Schema per f_spiaggia_reservations — prenotazioni ombrellone Spiagge.it.

    Source: dump JSON completo Spiagge.it (Panorama Beach), tabella reservations.
    Lifecycle SNAPSHOT full-replace (natural_key societa_id: ogni dump è il DB
    intero, il DELETE chirurgico su societa_id='INTUR' svuota la tabella).
    raw_object_id = FK a f_raw_objects, stampato dal path `promote`.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    license_code: Optional[str] = None
    spot_type: Optional[str] = None
    spot_name: Optional[str] = None
    status: Optional[int] = None
    seasonal: bool = False
    deleted: bool = False
    online: bool = False
    hotel: Optional[str] = None
    hotel_room: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    beds: Optional[int] = None
    chairs: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    list_total: Optional[float] = None
    paid_total: Optional[float] = None
    gross_booking_value: Optional[float] = None
    discount: Optional[float] = None
    channel: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_company: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaCashFlowRow(BaseModel):
    """Schema per f_spiaggia_cash_flows — movimenti cassa Spiagge.it.

    amount: float con segno (negativo = storno). method = codice intero grezzo,
    method_label = decodifica best-effort (legenda Spiagge.it ignota, vedi
    METHOD_LABELS nel parser). Lifecycle SNAPSHOT full-replace come reservations.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    reservation_id: Optional[int] = None
    method: Optional[int] = None
    method_label: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[_Date] = None
    receipt_id: Optional[int] = None
    invoice_id: Optional[int] = None
    deleted: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaSpotRow(BaseModel):
    """Schema per f_spiaggia_spots — mappa postazioni (ombrelloni + elementi).

    Tabella-dimensione: la mappa fisica della spiaggia. Lifecycle SNAPSHOT
    full-replace come reservations.
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    id: int
    uuid: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    sector: Optional[int] = None
    price_list_id: Optional[int] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    element_type: Optional[str] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaCorrispettivoRow(BaseModel):
    """Schema per f_spiaggia_corrispettivi — corrispettivi RT giornalieri INTUR.

    1 riga/giorno dal Registro Corrispettivi Spiaggia. Split per aliquota IVA:
    22% = spiaggia, 10% = bar. Lifecycle SNAPSHOT full-replace per anno
    (natural_key societa_id+anno). NON include gli alloggiati (= PMS, societa ORTI).
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    data: _Date
    anno: int
    mese: int
    corrispettivo_spiaggia: float
    corrispettivo_bar: float
    corrispettivo_totale: float
    rt_matricola: Optional[str] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
    hash_riga: str
    data_caricamento: datetime


class SpiaggiaFbOrdineRow(BaseModel):
    """Schema per f_spiaggia_fb_ordini — prima nota F&B bar spiaggia (Moolty).

    Per-scontrino: un ordine/pagamento per riga. Il bar spiaggia è INTUR.
    Lifecycle APPEND (dedup file-level via content-hash in intake; hash_riga per traccia).
    """

    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    location_id: Optional[str] = None
    oggetto_id: Optional[str] = None
    funzione_id: Optional[str] = None
    data_ora: datetime
    data: _Date
    metodo: Optional[str] = None
    entrata: Optional[float] = None
    uscita: Optional[float] = None
    pagato: bool = False
    rata: Optional[str] = None
    causale: Optional[str] = None
    descrizione: Optional[str] = None
    ordine_id: Optional[str] = None
    mese_report: Optional[str] = None
    raw_object_id: Optional[str] = None
    file_sorgente: str
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
