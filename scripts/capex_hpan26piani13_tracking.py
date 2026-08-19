"""Costruisce HPAN26PIANI1-3_Tracking.xlsx — cockpit CapEx (skill progetto-capex).

    python scripts/capex_hpan26piani13_tracking.py              # costruisce in output/
    python scripts/capex_hpan26piani13_tracking.py --upload     # e aggiorna il file su Drive IN PLACE

L'upload riscrive sempre lo stesso fileID: il link non cambia mai, niente _v2.
Non lanciarlo mentre il file è aperto in Excel.
"""
import io
import os
import sys
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from workspace.drive import get_drive_reader

SUBJ = "gm@panoramagroup.it"          # legge le fonti nella cartella condivisa
ROOT = "1tkcXApTFd2YTLzd0fPz5toYT51SVdC9P"   # cartella interna 04_progetti/Investimenti2026/HPAN26PIANI1-3
CONDIVISA = "11UJtN9fmqMsW1MSxzxYNvaOilq8ZtMLj"
FOLDERS = {
    "Preventivi": "1cS9cA4vkB6TBxtCox8TLxblExe8RD9UM",
    "Fatture":    "1s19UiUWkwNbdL0xOVZSAhDejx8y5pIto",
    "Fornitori":  "1Rw3boleohfjxoLkRYQsLL8Y8vPdB9uIV",
    "OOS":        "1xmXzdqT2J6NI3qzPmRq3MZkgug_spy99",
    "Contesto":   "1goHb0iX9oxMz95TSMX7vLJhxb5VVHCB5",
}
BUDGET_XLSX = "1W2KSC7lgUK9MjTNzR7_zLqZrJyIC78Iq"
COMPAR_XLSX = "1MIfXU4uC4NMQb7mF-40zOaQO36KAV-mP"
N_CAM = 33

# ---------- palette ----------
BLU   = "1F3864"
AZZ   = "D9E2F3"
GRIGIO= "F2F2F2"
GIALLO= "FFF2CC"
VERDE = "E2EFDA"
EUR   = '#,##0.00\\ "€"'
PCT   = '0.0"%"'
H_FONT = Font(bold=True, color="FFFFFF", size=10)
H_FILL = PatternFill("solid", fgColor=BLU)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def header(ws, row, cols, widths=None):
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.font, cell.fill, cell.border = H_FONT, H_FILL, BOX
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    if widths:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def titolo(ws, testo, ncol):
    c = ws.cell(row=1, column=1, value=testo)
    c.font = Font(bold=True, size=13, color=BLU)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(ncol, 2))
    ws.row_dimensions[1].height = 22


# ---------- sorgenti ----------
r = get_drive_reader(SUBJ)
wb_b = openpyxl.load_workbook(io.BytesIO(r.files().get_media(fileId=BUDGET_XLSX).execute()), data_only=True)
wb_c = openpyxl.load_workbook(io.BytesIO(r.files().get_media(fileId=COMPAR_XLSX).execute()), data_only=True)
ws_cam, ws_bud, ws_cmp = wb_b["Camera tipo"], wb_b["BUDGET 2026-2027"], wb_c["comparativo"]

# comparativo: riga -> (reale/cam, delta%, fonte, etichetta)
cmp_rows = {}
for i in range(2, ws_cmp.max_row + 1):
    v = [ws_cmp.cell(row=i, column=j).value for j in (2, 7, 8, 9, 10)]
    if v[0]:
        cmp_rows[i] = v  # voce, reale, delta, fonte, etichetta

def cmp_for(art):
    """art camera-tipo -> riga comparativo (17 e 18 sono fusi nella riga 18)."""
    if art <= 17:
        return cmp_rows.get(art + 1)
    if art == 18:
        return cmp_rows.get(18)
    return cmp_rows.get(art)

wb = openpyxl.Workbook()

# ══════════════════════════════ 1. Summary ══════════════════════════════
ws = wb.active
ws.title = "Summary"
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 42
ws.column_dimensions["C"].width = 20
ws.column_dimensions["D"].width = 20
ws.column_dimensions["E"].width = 62
ws.sheet_view.showGridLines = False

def sec(row, testo):
    c = ws.cell(row=row, column=2, value=testo)
    c.font = Font(bold=True, size=11, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=BLU)
    for col in range(2, 6):
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=BLU)
    ws.row_dimensions[row].height = 20

def kv(row, k, v, nf=None, nota=None, bold=False, fill=None):
    ck = ws.cell(row=row, column=2, value=k)
    ck.font = Font(bold=bold, size=10)
    cv = ws.cell(row=row, column=3, value=v)
    cv.font = Font(bold=bold, size=10)
    if nf:
        cv.number_format = nf
    if fill:
        for col in (2, 3, 4):
            ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=fill)
    if nota:
        cn = ws.cell(row=row, column=5, value=nota)
        cn.font = Font(size=9, color="595959", italic=True)
    return cv

t = ws.cell(row=1, column=2, value="HPAN26PIANI1-3 — COCKPIT ECONOMICO")
t.font = Font(bold=True, size=18, color=BLU)
s = ws.cell(row=2, column=2, value="2026/2027 Ristrutturazione Piano 3 e Piano 1 · Hotel Panorama, Maiori (SA)")
s.font = Font(size=11, color="595959")
ws.row_dimensions[1].height = 26

sec(4, "IDENTITÀ DEL PROGETTO")
kv(5, "Project ID", "HPAN26PIANI1-3", nota="stesso id di cronoprogramma, verbali e repo")
kv(6, "Committente", "Intur Srl", nota="UNA sola società: le fatture vanno intestate qui")
kv(7, "Perimetro", "Intero quadro economico", nota="camere P1+P3, VARI, imprevisti, spese tecniche")
kv(8, "Camere", f"{N_CAM} (13 al P1 + 20 al P3)")
kv(9, "Convenzione importi", "IMPONIBILE (IVA esclusa)", nota="il budget è IVA esclusa: preventivi e fatture vanno registrati allo stesso modo, o il confronto non regge")
kv(10, "Project Management", "Hospitality Project — Filippo Covili Faggioli")
kv(11, "Direzione Lavori", "Ing. Pisacane")
kv(12, "Ultimo aggiornamento", "→ aggiornato dallo script di riconciliazione")

sec(14, "BUDGET (fonte: 260722 budget_cameratipopignocchi.xlsx)")
kv(15, "Camere Piano Primo (13)", 851955, EUR)
kv(16, "Camere Piano Terzo (20)", 1330700, EUR)
kv(17, "VARI (facciate retro, ascensori, garage)", 330000, EUR)
kv(18, "Subtotale lavori", 2512655, EUR, bold=True, fill=GRIGIO)
kv(19, "Imprevisti 5%", 125632.75, EUR)
kv(20, "Spese tecniche e oneri", 86500, EUR)
kv(21, "BUDGET TOTALE", 2724787.75, EUR, bold=True, fill=GIALLO)
kv(22, "€/camera — solo lavori camere", 66141.06, EUR, nota="2.182.655 € ÷ 33")
kv(23, "€/camera — tutto compreso", "=C21/33", EUR,
   nota="benchmark HPAN25: 106.320 €/cam (cantiere completo 1.063.199 € ÷ 10 camere) → −22%. "
        "NON è una condanna: quelle 10 erano conversione da ristorante costruita da zero, queste sono "
        "restyling su camere esistenti, e uno sconto è legittimo. La domanda giusta non è «il budget è "
        "basso» ma «il 22% è lo sconto giusto fra un da-zero e un restyling»: è una valutazione tecnica "
        "da porre a chi fa il capitolato, non un calcolo.")

sec(24, "AVANZAMENTO ECONOMICO (si ricalcola dai fogli sotto)")
kv(25, "IMPEGNO — preventivi e contratti", "=SUM(Tracking_Fornitori!F3:F400)+SUM(Tracking_Fornitori!H3:H400)", EUR,
   nota="quanto abbiamo promesso di spendere")
kv(26, "MATURATO — da SAL e consuntivi", "=SUM(Chiusura_Fornitori!F3:F400)", EUR,
   nota="lavoro eseguito e certificato, anche se non ancora fatturato — su HPAN25 Santelia aveva 33.422 € così")
kv(27, "COMPETENZA — fatturato", "=SUM(Tracking_Fornitori!J3:J400)", EUR,
   nota="quanto ci è stato fatturato")
kv(28, "CASSA — pagato", "=SUM(Chiusura_Fornitori!H3:H400)", EUR,
   nota="quanto è uscito davvero")
kv(29, "Da pagare (partite aperte)", "=SUM(Chiusura_Fornitori!I3:I400)", EUR)
kv(30, "Da fatturare (maturato non fatturato)", "=SUM(Chiusura_Fornitori!J3:J400)", EUR)
kv(31, "Residuo a budget", "=C21-MAX(C25,C26,C27)", EUR, bold=True, fill=VERDE,
   nota="budget − MAX(impegno, maturato, fatturato). Mai la somma: la fattura realizza il preventivo")
kv(32, "% budget impegnato", "=IF(C21=0,0,MAX(C25,C26,C27)/C21)", "0.0%")

sec(34, "STATO DEL PRESIDIO")
kv(35, "Fornitori censiti", "=COUNTA(Tracking_Fornitori!B3:B400)")
kv(36, "Voci ancora DA DECIDERE", '=COUNTIF(Scelte!J3:J400,"DA DECIDERE")', nota="foglio Scelte")
kv(37, "Documenti archiviati", "=COUNTA(Documents!B3:B400)")
kv(38, "Work-package scoperti", '=COUNTIF(Scope_Items!J3:J400,"SCOPERTO")', nota="nessun preventivo ricevuto")

sec(40, "DOVE SI DROPPANO I FILE — cartella interna Investimenti2026/HPAN26PIANI1-3")
kv(41, "Preventivi", "→ Preventivi_PIANI1-3", nota=f"https://drive.google.com/drive/folders/{FOLDERS['Preventivi']}")
kv(42, "Fatture", "→ FATTURE_PIANI1-3", nota=f"https://drive.google.com/drive/folders/{FOLDERS['Fatture']}")
kv(43, "Vista per fornitore", "→ 07_fornitori", nota=f"https://drive.google.com/drive/folders/{FOLDERS['Fornitori']}")
kv(44, "Fuori perimetro", "→ 99_OOS", nota=f"https://drive.google.com/drive/folders/{FOLDERS['OOS']}")
kv(45, "Archivio condiviso con PM/DL", "→ cartella \u00abRistrutturazione Piano 3 e Piano 1\u00bb",
   nota=f"https://drive.google.com/drive/folders/{CONDIVISA} — non si tocca: regole nel suo README")

# ══════════════════════════════ 2. Istruzioni ══════════════════════════════
ws = wb.create_sheet("Istruzioni")
ws.sheet_view.showGridLines = False
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 26
ws.column_dimensions["C"].width = 108
t = ws.cell(row=2, column=2, value="COME SI USA QUESTO FILE")
t.font = Font(bold=True, size=16, color=BLU)

ISTR = [
    ("", ""),
    ("A cosa serve", "Questo file NON è un archivio. È il cockpit: risponde a quattro domande — "
                     "cosa ci serve, chi ce lo dà, quanto costa, quanto abbiamo pagato."),
    ("", ""),
    ("Le due cartelle", "Ci sono due posti, con due ruoli diversi, e non vanno confusi.\n\n"
                        "CONDIVISA — «2026/2027 Ristrutturazione Piano 3 e Piano 1», con PM, DL e imprese.\n"
                        "È l'archivio documentale ufficiale: valgono le regole del suo README di giugno\n"
                        "(ECO_, PRG_, CTR_…). Non si riorganizza e non ci si aggiungono cartelle:\n"
                        "la usano anche gli altri.\n\n"
                        "INTERNA — Investimenti2026/HPAN26PIANI1-3, nostra.\n"
                        "È qui che vivono questo cockpit e le sue sorgenti. Un documento può stare in\n"
                        "entrambe: nella condivisa perché lo vedano i terzi, qui perché entri nei conti."),
    ("", ""),
    ("Le 4 domande", "1. COSA CI SERVE  → foglio Scope_Items (i work-package a budget)\n"
                     "2. COSA SCEGLIAMO → foglio Scelte (una riga per voce della camera tipo)\n"
                     "3. CHI CE LO DÀ e QUANTO COSTA → fogli Tracking_Fornitori e Documents\n"
                     "4. QUANTO ABBIAMO PAGATO → foglio Chiusura_Fornitori"),
    ("", ""),
    ("Il ciclo di vita", "Ogni fornitore percorre sempre la stessa sequenza, e non si torna indietro:\n\n"
                        "IMPEGNO      preventivo ricevuto / ordine firmato\n"
                        "COMPETENZA   fattura emessa dal fornitore\n"
                        "CASSA        bonifico eseguito\n"
                        "CHIUSURA     lavoro finito e tutto pagato"),
    ("", ""),
    ("Cosa fare quando…", "arriva un PREVENTIVO → mettilo in 01_Economico/Preventivi_PIANI1-3, poi segnalalo\n"
                          "arriva una FATTURA   → mettila in 01_Economico/FATTURE_PIANI1-3, poi segnalala\n"
                          "si FIRMA un ordine   → PDF in 07_fornitori/F*/02_ordini_contratti\n"
                          "si SCEGLIE un fornitore → aggiorna la riga nel foglio Scelte\n"
                          "arriva una fattura non pertinente → 99_OOS + riga in OOS_Out_Of_Scope"),
    ("", ""),
    ("Le due regole che\nnon si violano", "1. Un fornitore non è «scelto» finché non c'è un ordine firmato. Prima è un candidato, "
                          "anche se ha il prezzo migliore.\n\n"
                          "2. Il totale di un fornitore è il MAGGIORE tra preventivato e fatturato, mai la somma: "
                          "la fattura realizza il preventivo, sommarli conta due volte la stessa spesa."),
    ("", ""),
    ("Importi", "Tutto IVA esclusa (imponibile), perché il budget è imponibile. Se registri un totale documento "
                "con IVA, il confronto con il budget salta."),
    ("", ""),
    ("La colonna\nbenchmark", "«Benchmark HPAN25 · solo confronto» riporta i prezzi unitari realmente pagati sulle 10 camere "
                "del primo piano fatte nel 2025-26 (progetto HPAN25PIANO1, ~1,2 M€, cantiere chiuso e separato).\n\n"
                "Serve a capire se una voce di budget regge alla prova dei fatti — nient'altro. "
                "È testo, non entra in nessuna somma, e nessun costo del 2025 fa parte dei 2,72 M€ di questo progetto. "
                "I due cantieri restano contabilmente separati."),
    ("", ""),
    ("Note di credito", "Una nota di credito si registra con importo NEGATIVO. Non è un dettaglio formale: "
                "negli export Esolver le note di credito escono col segno positivo, distinte solo dal tipo "
                "documento 721 (716 = fattura, 710 = differita). Chi somma senza guardare il tipo non sottrae "
                "gli storni, li somma.\n\n"
                "Sul cantiere HPAN25 questo errore gonfiava il 2025 del 143% (946.296 € grezzi contro "
                "388.765 € reali). Qui non deve succedere."),
    ("", ""),
    ("Come si chiamano\ni file", "Convenzione unica, imposta all'origine — si chiede al fornitore, non si sistema dopo:\n\n"
                "    AAAA-MM-GG_Fornitore_TipoDoc_Numero.pdf\n\n"
                "Serve perché archivio e contabilità si possano riconciliare. Su HPAN25 non c'era: 31 documenti "
                "su 68 senza PDF archiviato (~453.000 €) e 12 fatture in doppia copia, perché lo stesso "
                "documento arriva sia come PDF di cortesia del fornitore sia come resa ministeriale SDI.\n\n"
                "Un duplicato NON si riconosce dall'hash del file: le due copie hanno hash diversi anche a "
                "contenuto identico. Si riconosce da fornitore + numero + data + totale."),
    ("", ""),
    ("Reverse charge", "I fornitori edili fatturano in reverse charge (art. 17): su quelle fatture "
                "totale e imponibile COINCIDONO, perché l'IVA non è applicata. AMCN è tutta così.\n\n"
                "Non è un errore e non va corretto: se confronti un fornitore in reverse charge e uno "
                "ordinario e i conti tornano solo sul primo, la causa è questa."),
    ("", ""),
    ("I prezzi unitari\nsi copiano a mano", "In contabilità il dettaglio di riga NON esiste: su 2.831 righe di fatture "
                "la descrizione articolo è compilata su 5. Lavabi, rubinetteria, mobili bagno — il prezzo "
                "unitario vive solo dentro il PDF della fattura elettronica.\n\n"
                "Per questo c'è il foglio Righe_Documento: è l'unico posto dove quel dato può esistere. "
                "La contabilità non lo darà mai."),
    ("", ""),
    ("Consuntivi\nnon sono fatture", "Un SAL o un consuntivo dice quanto lavoro è stato ESEGUITO. Una fattura dice "
                "quanto è stato CHIESTO. Non coincidono quasi mai, e il primo corre avanti al secondo.\n\n"
                "Su HPAN25 il consuntivo Santelia valeva 103.422 € mentre in contabilità ce n'erano 70.000: "
                "33.422 € di lavori già maturati e non ancora fatturati, invisibili a chi guardava solo le fatture. "
                "E Santelia era l'unico fornitore verificabile, perché il suo consuntivo era per caso archiviato.\n\n"
                "Per questo in Chiusura_Fornitori c'è «€ Maturato»: appena arriva un SAL, si copia lì. "
                "Senza, l'avanzamento del cantiere risulta più indietro di quanto sia, e il costo più basso."),
    ("", ""),
    ("Quanto è costata\ndavvero una camera", "Il cantiere HPAN25 completo vale **1.063.199 €** per **10 camere** "
                "(115-125, la 117 non esiste): **106.320 € a camera**.\n\n"
                "    886.740   perimetro capitalizzato, anticipi, progettazione\n"
                "  + 100.307   arredi e attrezzature sotto 516 € (Amazon, Sklum, Leroy Merlin, Indel B)\n"
                "  +  42.730   materiali di manutenzione\n"
                "  =1.029.777   cantiere\n"
                "  +  33.422   Santelia maturato e non fatturato\n"
                "  =1.063.199   cantiere completo\n\n"
                "Gli arredi sotto 516 € stanno su conti di spesa corrente e a prima vista sembrano gestione "
                "ordinaria. Non lo sono: sono le camere.\n\n"
                "Il budget di questo progetto è 82.569 €/camera, cioè **−22%**. Lo sconto può essere legittimo — "
                "quelle erano costruite da zero convertendo un ristorante, queste sono restyling su camere "
                "esistenti — ma va deciso, non subito: il 22% è una domanda per chi scrive il capitolato."),
    ("", ""),
    ("Il benchmark edile\nnon vale", "Nel foglio Scope_Items l'edile AMCN NON ha un benchmark utilizzabile, e la casella "
                "dice «NON COMPARABILE» apposta.\n\n"
                "Il comparativo del 18/08 segnava +53% sul budget edile. Ma il computo consuntivo AMCN del 30/06 "
                "contiene anche balconi su Via Capitolo e Via S. Tecla, intonaci su facciate esterne, nolo "
                "ponteggio a mese, tinteggiatura ringhiere, e lavorazioni parziali sulle camere 105 e 106-107 "
                "(toccate dal computo, ma non consegnate). Il numeratore è gonfiato di opere che non sono "
                "camere: il +53% misura un perimetro diverso da quello che sembra.\n\n"
                "Il computo AMCN è chiuso e definitivo — certificato di pagamento finale «rata n. 4 ed ultima» "
                "del 30/06, DL ing. Pisacane — quindi il problema non è che manchino dati: è che quei dati "
                "misurano un perimetro diverso. Le camere consegnate l'anno scorso sono 10 (115-125, la 117 "
                "non esiste); le 13 del primo piano sono quelle di QUESTO progetto.\n\n"
                "Finché non si scorporano le 117 voci di tariffa, sul budget edile — 775.500 €, il 28% del "
                "progetto — non abbiamo un termine di paragone. Meglio saperlo che avere un numero falso."),
    ("", ""),
    ("Chi aggiorna", "Le colonne grigie si ricalcolano dai documenti su Drive. Le colonne gialle sono umane: "
                     "«Lavoro finito?», «Chi lo sa», «Decisa da», le note. Riempile solo quando l'informazione è certa; "
                     "una cella vuota è un'informazione onesta, una cella inventata no."),
    ("", ""),
    ("Attenzione", "Non aprire questo file mentre lo script di riconciliazione ci sta scrivendo. "
                   "E non creare _v2 / _v3: si aggiorna sempre questo file, così il link non cambia mai."),
]
row = 4
for k, v in ISTR:
    if not k and not v:
        row += 1
        continue
    ck = ws.cell(row=row, column=2, value=k)
    ck.font = Font(bold=True, size=10, color=BLU)
    ck.alignment = Alignment(vertical="top", wrap_text=True)
    cv = ws.cell(row=row, column=3, value=v)
    cv.alignment = Alignment(vertical="top", wrap_text=True)
    cv.font = Font(size=10)
    ws.row_dimensions[row].height = max(16, 13 * (v.count("\n") + 1 + len(v) // 105))
    row += 1

# ══════════════════════════════ 3. Scope_Items ══════════════════════════════
ws = wb.create_sheet("Scope_Items")
titolo(ws, "COSA CI SERVE — work-package a budget (fonte: BUDGET 2026-2027)", 11)
COLS = ["Art.", "Ambito", "Work-package", "Fornitore a budget", "UdM", "Q.tà",
        "€ Unitario", "€ Budget", "Benchmark HPAN25 · solo confronto", "Stato", "Note"]
header(ws, 2, COLS, [6, 14, 46, 22, 6, 8, 14, 16, 18, 16, 40])

# art budget -> riga comparativo. P1: 1 camera tipo · 2 edile · 3 elettrici · 4 VDA · 5 termo
#                                 P3: 6 camera tipo · 7 edile · 8 elettrici · 9 VDA · 10 termo
CMP_MACRO = {2: 39, 7: 39, 5: 40, 10: 40, 3: 41, 8: 41, 4: 42, 9: 42}

BUD_ROWS = [(4, "PIANO PRIMO"), (5, "PIANO PRIMO"), (6, "PIANO PRIMO"), (7, "PIANO PRIMO"), (8, "PIANO PRIMO"),
            (11, "PIANO TERZO"), (12, "PIANO TERZO"), (13, "PIANO TERZO"), (14, "PIANO TERZO"), (15, "PIANO TERZO"),
            (18, "VARI"), (19, "VARI"), (20, "VARI"),
            (26, "SPESE TECNICHE"), (28, "SPESE TECNICHE"), (31, "SPESE TECNICHE"),
            (32, "SPESE TECNICHE"), (33, "SPESE TECNICHE")]

out = 3
for src, ambito in BUD_ROWS:
    art  = ws_bud.cell(row=src, column=1).value
    forn = ws_bud.cell(row=src, column=2).value
    desc = ws_bud.cell(row=src, column=3).value
    udm  = ws_bud.cell(row=src, column=4).value
    qta  = ws_bud.cell(row=src, column=5).value
    pu   = ws_bud.cell(row=src, column=6).value
    tot  = ws_bud.cell(row=src, column=7).value
    nota = ws_bud.cell(row=src, column=8).value or ""
    arti = int(art) if isinstance(art, (int, float)) else None
    # Override sui benchmark macro che il CME del 30/06 ha smentito (vedi Istruzioni)
    OVERRIDE = {
        2: "NON COMPARABILE — vedi Istruzioni",
        7: "NON COMPARABILE — vedi Istruzioni",
        5: "ORDINE DI GRANDEZZA — regge, non è una precisione",
        10: "ORDINE DI GRANDEZZA — regge, non è una precisione",
    }
    NOTA_OVR = {
        2: "Il +53% del comparativo 18/08 non regge: il CME AMCN del 30/06 include balconi, "
           "facciate, ponteggio e lavorazioni parziali su 105 e 106-107. Numeratore gonfiato "
           "di opere che non sono costo-camera. Da riverificare scorporando le 117 voci.",
        7: "Idem art. 2 — benchmark edile contaminato da opere esterne e camere extra.",
        5: "103.421,73 consuntivo − 13.600 di infrastrutture (montante antincendio 9.000, "
           "colonna fecale 2.800, caldaia provvisoria 1.800) = 89.821,73 ÷ 10 = 8.982 €/cam "
           "contro 9.000 a budget: il +15% del comparativo era l'infrastruttura. MA dentro ci sono "
           "29.900 di pompa di calore 45 kW + 21 fancoil, un terzo del totale, dimensionata su "
           "un'ala di 10 camere: su 33 camere e tre piani la macchina non si moltiplica per 3,3. "
           "Serve una verifica impiantistica, non una proporzione.",
        10: "Idem art. 5.",
    }
    ric = ""
    if arti in OVERRIDE:
        ric = OVERRIDE[arti]
        nota = (NOTA_OVR[arti] + (" · " + str(nota) if nota else ""))
    elif arti in CMP_MACRO:
        cr = cmp_rows.get(CMP_MACRO[arti])
        if cr:
            ric = f"{cr[4]}" + (f" ({cr[2]:+.0f}%)" if isinstance(cr[2], (int, float)) else "")
    vals = [arti, ambito, (desc or "").strip(), (str(forn).strip() if forn else "TBD"),
            udm, qta, pu, tot, ric, "SCOPERTO", nota]
    for i, v in enumerate(vals, 1):
        c = ws.cell(row=out, column=i, value=v)
        c.border = BOX
        c.font = Font(size=10)
        c.alignment = Alignment(vertical="center", wrap_text=(i in (3, 11)))
        if i in (7, 8):
            c.number_format = EUR
        if i == 10:
            c.fill = PatternFill("solid", fgColor=GRIGIO)
    ws.row_dimensions[out].height = 26
    out += 1

tr = out + 1
ws.cell(row=tr, column=3, value="TOTALE PERIMETRO").font = Font(bold=True, size=10)
tc = ws.cell(row=tr, column=8, value=f"=SUM(H3:H{out-1})")
tc.font = Font(bold=True, size=10)
tc.number_format = EUR
tc.fill = PatternFill("solid", fgColor=GIALLO)
ws.cell(row=tr + 1, column=3, value="Imprevisti 5% (non allocati a un fornitore)").font = Font(size=10, italic=True)
ic = ws.cell(row=tr + 1, column=8, value=125632.75)
ic.number_format = EUR
ic.font = Font(size=10, italic=True)
ws.cell(row=tr + 2, column=3, value="BUDGET TOTALE").font = Font(bold=True, size=11)
gc = ws.cell(row=tr + 2, column=8, value=f"=H{tr}+H{tr+1}")
gc.font = Font(bold=True, size=11)
gc.number_format = EUR
gc.fill = PatternFill("solid", fgColor=GIALLO)

dv = DataValidation(type="list", formula1='"SCOPERTO,PREVENTIVI IN CORSO,SOLO IMPEGNO,IN CORSO,COMPLETO"', allow_blank=True)
ws.add_data_validation(dv)
dv.add(f"J3:J{out-1}")

# ══════════════════════════════ 4. Scelte ══════════════════════════════
ws = wb.create_sheet("Scelte")
titolo(ws, "COSA SCEGLIAMO — una riga per voce della camera tipo (× 33 camere)", 15)
COLS = ["Art.", "Ambito", "Voce", "UdM", "Q.tà/cam", "€ Unitario", "€ Budget/cam", f"€ Budget {N_CAM} cam",
        "Fornitore candidato", "Stato scelta", "Alternative valutate", "Decisa il", "Decisa da",
        "Benchmark HPAN25 · solo confronto", "Doc di riferimento", "Note"]
header(ws, 2, COLS, [6, 10, 40, 6, 9, 13, 14, 16, 20, 16, 26, 12, 14, 30, 26, 34])

ambito = "CAMERA"
out = 3
for src in range(6, 59):
    art = ws_cam.cell(row=src, column=1).value
    tip = ws_cam.cell(row=src, column=2).value
    des = ws_cam.cell(row=src, column=3).value
    if des and not art and not tip:
        if str(des).strip().upper() == "BAGNO":
            ambito = "BAGNO"
        continue
    if not isinstance(art, (int, float)):
        continue
    arti = int(art)
    udm = ws_cam.cell(row=src, column=4).value
    qta = ws_cam.cell(row=src, column=5).value
    pu  = ws_cam.cell(row=src, column=6).value
    tot = ws_cam.cell(row=src, column=7).value
    forn = (str(tip).strip() if tip else "TBD")
    stato = "DA DECIDERE" if forn.upper() in ("TBD", "VARI", "") else "CANDIDATO"
    cr = cmp_for(arti)
    ric, doc = "", ""
    if cr:
        et = cr[4] or ""
        dl = f" ({cr[2]:+.1f}%)" if isinstance(cr[2], (int, float)) else ""
        re = f" · reale {cr[1]:,.0f} €".replace(",", ".") if isinstance(cr[1], (int, float)) else ""
        ric = f"{et}{dl}{re}"
        doc = cr[3] or ""
    vals = [arti, ambito, (des or "").strip(), udm, qta, pu, tot, (tot or 0) * N_CAM,
            forn, stato, "", None, "", ric, doc, ""]
    for i, v in enumerate(vals, 1):
        c = ws.cell(row=out, column=i, value=v)
        c.border = BOX
        c.font = Font(size=10)
        c.alignment = Alignment(vertical="center", wrap_text=(i in (3, 11, 14, 15, 16)))
        if i in (6, 7, 8):
            c.number_format = EUR
        if i == 12:
            c.number_format = "dd/mm/yyyy"
        if i in (11, 12, 13, 16):
            c.fill = PatternFill("solid", fgColor=GIALLO)
        if i == 10:
            c.fill = PatternFill("solid", fgColor=("FCE4D6" if stato == "DA DECIDERE" else GRIGIO))
    ws.row_dimensions[out].height = 26
    out += 1

tr = out + 1
ws.cell(row=tr, column=3, value="TOTALE CAMERA TIPO").font = Font(bold=True, size=10)
c = ws.cell(row=tr, column=7, value=f"=SUM(G3:G{out-1})")
c.number_format = EUR
c.font = Font(bold=True, size=10)
c.fill = PatternFill("solid", fgColor=GIALLO)
c = ws.cell(row=tr, column=8, value=f"=SUM(H3:H{out-1})")
c.number_format = EUR
c.font = Font(bold=True, size=10)
c.fill = PatternFill("solid", fgColor=GIALLO)

dv = DataValidation(type="list", formula1='"DA DECIDERE,CANDIDATO,SCELTO,ORDINATO,CONSEGNATO"', allow_blank=True)
ws.add_data_validation(dv)
dv.add(f"J3:J{out-1}")

# ══════════════════════════════ 5. Tracking_Fornitori ══════════════════════════════
ws = wb.create_sheet("Tracking_Fornitori")
titolo(ws, "ARCHIVIO DOCUMENTI PER FORNITORE — una riga per F-code", 13)
COLS = ["Cod", "Ragione Sociale", "Macro", "Scope", "# Prev", "€ Prev", "# Contr", "€ Contr",
        "# Fatt", "€ Fatt", "Totale €", "Status", "Cartella F* (Drive)"]
header(ws, 2, COLS, [8, 30, 16, 34, 8, 15, 8, 15, 8, 15, 16, 18, 18])
for rr in range(3, 60):
    f = ws.cell(row=rr, column=11, value=f"=MAX(F{rr},J{rr})")
    f.number_format = EUR
    for cc in (6, 8, 10):
        ws.cell(row=rr, column=cc).number_format = EUR
dv = DataValidation(type="list", formula1='"SCOPERTO,SOLO IMPEGNO,SOLO COMPETENZA,COMPLETO"', allow_blank=True)
ws.add_data_validation(dv)
dv.add("L3:L400")
n = ws.cell(row=4, column=2, value="→ le righe nascono quando arriva il primo documento di quel fornitore. "
                                   "I fornitori del budget sono candidati, non ancora ingaggiati.")
n.font = Font(size=10, italic=True, color="808080")

# ══════════════════════════════ 6. Documents ══════════════════════════════
ws = wb.create_sheet("Documents")
titolo(ws, "OGNI DOCUMENTO, UNA RIGA", 10)
COLS = ["Cod", "Fornitore", "Tipo", "N° documento", "Data", "€ Imponibile", "Descrizione",
        "File su Drive", "Sostituisce", "Note"]
header(ws, 2, COLS, [8, 26, 14, 22, 12, 16, 44, 20, 18, 30])
for rr in range(3, 400):
    ws.cell(row=rr, column=5).number_format = "dd/mm/yyyy"
    ws.cell(row=rr, column=6).number_format = EUR
dv = DataValidation(type="list", formula1='"Preventivo,Ordine,Contratto,Fattura,Nota di credito,SAL,Proforma"', allow_blank=True)
ws.add_data_validation(dv)
dv.add("C3:C400")
n = ws.cell(row=4, column=2, value="→ «Sostituisce» serve per le revisioni: un preventivo Rev02 sostituisce il Rev01, "
                                   "e solo il più recente entra nei totali.   "
                                   "→ «N° documento» si copia ESATTAMENTE come sta sul documento (589 / 00, 1/29, "
                                   "V126-07401): la riconciliazione con la contabilità normalizza da sola, "
                                   "ma solo se parte dall'originale.")
n.font = Font(size=10, italic=True, color="808080")

# ══════════════════════════════ 7. Chiusura_Fornitori ══════════════════════════════
ws = wb.create_sheet("Chiusura_Fornitori")
titolo(ws, "IL COCKPIT OPERATIVO — abbiamo finito? quanto resta? chi va pagato?", 15)
COLS = ["Cod", "Fornitore", "Macro", "Scope", "€ Prev/Contratto", "€ Maturato (SAL/consuntivo)",
        "€ Fatturato", "€ Pagato", "€ Da Pagare", "€ Da Fatturare", "Stato Operativo",
        "Lavoro Finito?", "Ultima Evidenza", "Chi Lo Sa", "Prossima Azione", "Note"]
header(ws, 2, COLS, [8, 26, 15, 28, 17, 19, 15, 15, 15, 16, 18, 14, 16, 16, 30, 30])
for rr in range(3, 60):
    for cc in (5, 6, 7, 8, 9):
        ws.cell(row=rr, column=cc).number_format = EUR
    # da fatturare: dal maturato se c'è, altrimenti ripiega sul preventivo
    f = ws.cell(row=rr, column=10, value=f"=IF(F{rr}>0,MAX(F{rr}-G{rr},0),MAX(E{rr}-G{rr},0))")
    f.number_format = EUR
    ws.cell(row=rr, column=13).number_format = "dd/mm/yyyy"
    for cc in (6, 12, 14, 15, 16):
        ws.cell(row=rr, column=cc).fill = PatternFill("solid", fgColor=GIALLO)
dv = DataValidation(type="list",
                    formula1='"SCOPERTO,SOLO IMPEGNO,DA FATTURARE,DA PAGARE,LAVORI IN CORSO,CHIUSO,DUBBIO"',
                    allow_blank=True)
ws.add_data_validation(dv)
dv.add("K3:K400")
dv2 = DataValidation(type="list", formula1='"SI,NO,PARZIALE"', allow_blank=True)
ws.add_data_validation(dv2)
dv2.add("L3:L400")
n = ws.cell(row=4, column=2, value="→ «€ Pagato» e «€ Da Pagare» arrivano dalle partite Esolver di Intur Srl. "
                                   "«€ Maturato» si copia dal SAL o dal consuntivo del fornitore: è lavoro eseguito, "
                                   "non ancora fatturato. Le colonne gialle le riempie una persona, non lo script.")
n.font = Font(size=10, italic=True, color="808080")

# ══════════════════════ 8. Righe_Documento ══════════════════════
ws = wb.create_sheet("Righe_Documento")
titolo(ws, "PREZZI UNITARI — si copiano dai PDF, la contabilità non li ha", 13)
COLS = ["Cod", "Fornitore", "N° documento", "Data", "Art. Scelte", "Voce",
        "Descrizione articolo", "UdM", "Q.tà", "€ Unitario", "€ Riga", "Ambito", "Note"]
header(ws, 2, COLS, [8, 24, 20, 12, 11, 30, 44, 7, 9, 14, 15, 12, 28])
for rr in range(3, 400):
    ws.cell(row=rr, column=4).number_format = "dd/mm/yyyy"
    for cc in (10, 11):
        ws.cell(row=rr, column=cc).number_format = EUR
n = ws.cell(row=4, column=2, value="→ «Art. Scelte» è il numero della voce nel foglio Scelte: è il ponte che permette "
                                   "di confrontare il prezzo pagato col budget di quella voce.")
n.font = Font(size=10, italic=True, color="808080")

# ══════════════════════════════ 9. OOS ══════════════════════════════
ws = wb.create_sheet("OOS_Out_Of_Scope")
titolo(ws, "FUORI PERIMETRO — documenti esclusi dai totali, ma tracciati", 7)
COLS = ["Fornitore", "N° documento", "Data", "€ Imponibile", "Perché è fuori perimetro",
        "Dove va invece", "File su Drive"]
header(ws, 2, COLS, [26, 22, 12, 16, 46, 28, 20])
for rr in range(3, 200):
    ws.cell(row=rr, column=3).number_format = "dd/mm/yyyy"
    ws.cell(row=rr, column=4).number_format = EUR

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "output", "HPAN26PIANI1-3_Tracking.xlsx")
TRACKING_FILE_ID = "1dV0WZLJru2N7PSBqE5IBCqqw5vNqBIYw"
WRITER = "stefano@panoramagroup.it"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

os.makedirs(os.path.dirname(OUT), exist_ok=True)
wb.save(OUT)
print("SAVED", OUT)
for name in wb.sheetnames:
    print("  foglio:", name)

if "--upload" in sys.argv:
    from googleapiclient.http import MediaIoBaseUpload
    from workspace.drive import get_drive_writer
    svc = get_drive_writer(WRITER)
    media = MediaIoBaseUpload(io.BytesIO(open(OUT, "rb").read()), mimetype=XLSX, resumable=False)
    meta = svc.files().update(fileId=TRACKING_FILE_ID, media_body=media,
                              fields="id,name,modifiedTime", supportsAllDrives=True).execute()
    print("AGGIORNATO IN PLACE:", meta)
else:
    print("\n(nessun upload — rilancia con --upload per aggiornare il file su Drive)")
