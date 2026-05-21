/**
 * Audit consumi F&B per la direzione — Hotel Panorama.
 *
 * Genera Google Form con 8 sezioni: Identità + 3 vertical + Coperti
 * mapping + Range operativi + Anomalie FYI + Catch-all.
 *
 * Setup:
 * 1. Vai su https://script.google.com
 * 2. Nuovo progetto
 * 3. Incolla TUTTO questo file
 * 4. Salva (Cmd+S)
 * 5. Esegui createAuditForm() (icona play)
 * 6. Autorizza Google Drive/Forms
 * 7. View > Logs (Cmd+Enter) → URL della Form + Sheet collegato
 * 8. Aggiorna FORM_URL in audit_consumi_dashboard.py
 */

function createAuditForm() {
  var form = FormApp.create('Audit consumi F&B — Hotel Panorama');
  form.setDescription(
    'Conferma i codici proposti per i 3 vertical F&B (Breakfast/Ristorante/Bar). ' +
    'Apri prima la Streamlit audit per vedere i numeri.'
  );
  form.setCollectEmail(true);
  form.setAllowResponseEdits(true);

  // --- S0: Identità
  form.addSectionHeaderItem().setTitle('Identità');
  form.addTextItem().setTitle('Nome e ruolo').setRequired(true);
  form.addDateItem().setTitle('Data di compilazione').setRequired(true);

  // --- S1: B1 Breakfast
  form.addPageBreakItem()
    .setTitle('S1 — Breakfast')
    .setHelpText('Vedi Streamlit pagina B1 Breakfast prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Breakfast?')
    .setChoiceValues([
      'SCBKFBB — Scorpori Breakfast B&B (HOTEL)',
      'SCBKFHB — Scorpori Breakfast HB (CVM)',
      'BRKADULT — Breakfast Adult',
      'BRKBABY — Breakfast Child',
      'BRKEXT — Breakfast Esterni Adult',
      'BRKEXTC — Breakfast Esterni Child',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Le 4 BU (HOTEL+RES+ANG+CVM) le aggreghi tutte o le tieni separate?')
    .setChoiceValues([
      'a) Aggregate tutte in un unico bucket breakfast',
      'b) Separate per BU (HOTEL breakfast, RES breakfast, ANG breakfast, CVM breakfast)',
      'c) Solo HOTEL+CVM (RES e ANG non hanno breakfast vero)',
      'd) Altro',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici breakfast da aggiungere o note');

  // --- S2: B2 Ristorante
  form.addPageBreakItem()
    .setTitle('S2 — Ristorante')
    .setHelpText('Vedi Streamlit pagina B2 Ristorante prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Ristorante Food?')
    .setChoiceValues([
      'RISLFOOD — Risto Lunch Food',
      'RISDFOOD — Risto Dinner Food',
      'RISTLUNC — Restaurant Lunch manuale',
      'RISTDINN — Restaurant Dinner manuale',
      'DINFOOD — Dinner Food generico',
      'LUNBAR — Lunch Bar',
      'RISBFOOD — Risto Bar Food',
      'BAN — Banqueting Food',
      'ROOMSERV — Room Service',
      'FERRAD — Party Ferragosto Adulti',
      'FERRBA — Party Ferragosto Bambini',
      'PASQAD — Pranzo di Pasqua',
      'PARTY — Party generico',
      'BRUNCH — Brunch Buffet',
      'APERIDIN — Aperidinner',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Gli eventi (FERRAD/FERRBA/PASQAD/PARTY/BRUNCH/APERIDIN) vanno…')
    .setChoiceValues([
      'a) Dentro B2 Ristorante (mescolati col regolare)',
      'b) Bucket "Eventi" separato',
      'c) Esclusi dal F&B (sono one-off)',
      'd) Misto',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('RISBFOOD (Risto Bar Food) — è food o bar?')
    .setChoiceValues([
      'a) Food (va in B2)',
      'b) Bar (va in B3)',
      'c) Misto',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici ristorante da aggiungere o note');

  // --- S3: B3 Bar/Beverage
  form.addPageBreakItem()
    .setTitle('S3 — Bar / Beverage')
    .setHelpText('Vedi Streamlit pagina B3 prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Bar/Beverage?')
    .setChoiceValues([
      'BAR — Bar generico',
      'BARHOTEL — Bar Hotel',
      'RISLBEVE — Risto Lunch Beverage',
      'RISLBEV — Risto Lunch Beverage (variant)',
      'RISDBEV — Risto Dinner Beverage',
      'DINBEV — Dinner Beverage',
      'BANB — Banqueting Beverage',
      'PROSECCO — Bottiglia Prosecco',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('BARHOTEL e BAR sono lo stesso codice o due diversi?')
    .setChoiceValues([
      'a) Stesso, fondiamoli',
      'b) Diversi (BARHOTEL = bar dell hotel, BAR = generico)',
      'c) Non lo so, da verificare',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici beverage da aggiungere o note');

  // --- S4: Coperti mapping
  form.addPageBreakItem()
    .setTitle('S4 — Coperti mapping')
    .setHelpText('Da dove leggi i coperti accurati?');

  form.addMultipleChoiceItem()
    .setTitle('Fonte coperti più accurata')
    .setChoiceValues([
      'a) Hoxell',
      'b) Excel syncato (Google Sheet RistoCube)',
      'c) Entrambi',
      'd) Altro',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Coperti BRK includono…')
    .setChoiceValues([
      'a) Solo clienti hotel B&B',
      'b) Clienti hotel B&B + esterni paganti (BRKADULT/EXT)',
      'c) Anche staff/dipendenti',
      'd) Altro',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Coperti LUNCH e DINNER sono separati?')
    .setChoiceValues([
      'a) Sì, sempre',
      'b) No, brunch e altri ibridi non distinti',
      'c) Solo lunch+dinner regolari, eventi conta a parte',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Note coperti');

  // --- S5: Range operativi
  form.addPageBreakItem()
    .setTitle('S5 — Range operativi')
    .setHelpText('Quali sono i tuoi target food/beverage cost realistici?');

  form.addMultipleChoiceItem()
    .setTitle('Target Food cost ristorante Panorama (auto-valutazione)')
    .setChoiceValues([
      'a) Pizzeria-level (~15%) — siamo molto economici',
      'b) Ristorante medio (25-35%) — siamo standard',
      'c) Top-tier (~38%) — siamo premium',
      'd) Altro (specifica nelle note)',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Target Beverage cost Panorama')
    .setChoiceValues([
      'a) Basic (10-15%)',
      'b) Medio (15-25%)',
      'c) Top-tier (25-30%)',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Target personali / esperienza diretta');

  // --- S6: Anomalie FYI
  form.addPageBreakItem()
    .setTitle('S6 — Anomalie FYI')
    .setHelpText('Conferma rapida delle 7 osservazioni dalla Streamlit.');

  var anomalie = [
    'FYI-1 — Storni UoM maggio 2025 (15 righe -€166k)',
    'FYI-2 — BANCHETTI reparto sotto-stimato vs revenue BAN',
    'FYI-3 — BAR_HOTEL reparto vuoto (drink da CANTINA)',
    'FYI-4 — 17 codici "da sospendere" da pianodeicontilavoro.xlsx',
    'FYI-5 — Codice orfano ACCFCI (€252) da classificare',
    'FYI-6 — Reparti non-F&B (DIPEND/HSK/MAN/etc) gestiti separati',
    'FYI-7 — Carico magazzino stagionale BRK luglio',
  ];
  for (var i = 0; i < anomalie.length; i++) {
    form.addMultipleChoiceItem()
      .setTitle(anomalie[i])
      .setChoiceValues(['✓ confermo', '✗ no, da rivedere', 'non lo so'])
      .setRequired(false);
  }
  form.addParagraphTextItem().setTitle('Note generali sulle anomalie');

  // --- S7: Catch-all
  form.addPageBreakItem().setTitle('S7 — Catch-all');
  form.addParagraphTextItem()
    .setTitle("C'è qualcosa che dovremmo guardare e non stiamo guardando? Codici/situazioni mancanti?");

  // Collega Google Sheet auto
  var ss = SpreadsheetApp.create('Audit consumi F&B — Risposte');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  Logger.log('Form URL: ' + form.getPublishedUrl());
  Logger.log('Form edit URL: ' + form.getEditUrl());
  Logger.log('Spreadsheet URL: ' + ss.getUrl());
}
