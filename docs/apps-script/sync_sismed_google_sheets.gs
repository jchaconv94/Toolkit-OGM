function normalizeAlmcod(value) {
  return (value || "").toString().replace(/[^0-9A-Za-z]/g, "").toUpperCase();
}

function facilityCodeFromAlmcod(almcod) {
  var code = normalizeAlmcod(almcod);

  // Formato comun: 06524F0101 => IPRESS base 06524.
  if (code.length >= 8 && code.substring(5, 6) === "F") {
    return code.substring(0, 5);
  }

  // Formato alfanumerico: 030S0501 => IPRESS base 030S05.
  if (code.length >= 6 && /[A-Z]/.test(code.substring(0, 6))) {
    return code.substring(0, 6);
  }

  return code.length >= 5 ? code.substring(0, 5) : code;
}

function splitReportedAlmcods(value) {
  if (!value) return [];
  return value.toString().split(",")
    .map(function(item) { return normalizeAlmcod(item); })
    .filter(function(item) { return item; });
}

function findExistingSheetByCode(ss, codigoBase) {
  var suffix = "-" + codigoBase;
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    var name = sheets[i].getName();
    if (name === codigoBase || name.slice(-suffix.length) === suffix) {
      return sheets[i];
    }
  }
  return null;
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);

    var reportedAlmcods = splitReportedAlmcods(
      e && e.parameter ? e.parameter.reported_almcods : ""
    );

    if (!data || (data.length === 0 && reportedAlmcods.length === 0)) {
      return ContentService.createTextOutput("OK:0 registros (payload vacio).")
        .setMimeType(ContentService.MimeType.TEXT);
    }

    var ultimaActualizacion = Utilities.formatDate(
      new Date(),
      "America/Lima",
      "dd/MM/yyyy HH:mm:ss"
    );

    var headers = [
      "ALMCOD", "DESC_ALM", "ID_Producto", "CODIGO_SIG", "Nombre",
      "Lote", "Fec_Vencim", "Reg_Sanitario",
      "TIPSUM", "DESC_TIPSUM", "FFINAN", "DESC_FFINAN",
      "Saldo", "Precio_Det", "Precio_Cab",
      "FECHA DEL EQUIPO", "ULTIMA ACTUALIZACION"
    ];

    var NUM_COLS = headers.length;
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    var grupos = {};
    data.forEach(function(item) {
      var alm_full = normalizeAlmcod(item.almcod || "00000");
      var alm_base = facilityCodeFromAlmcod(alm_full);

      if (!grupos[alm_base]) grupos[alm_base] = [];
      grupos[alm_base].push(item);
    });

    reportedAlmcods.forEach(function(almcod) {
      var alm_base = facilityCodeFromAlmcod(almcod);
      if (alm_base && !grupos[alm_base]) grupos[alm_base] = [];
    });

    var totalRegistros = 0;
    var hojasActualizadas = [];

    for (var codigoBase in grupos) {
      var registros = grupos[codigoBase];

      var descAlm = (registros.length > 0 ? (registros[0].desc_alm || codigoBase) : codigoBase)
        .toString()
        .trim();
      descAlm = descAlm.replace(" (CONSOLIDADO)", "");

      var nombreHoja = (descAlm + "-" + codigoBase)
        .replace(/[\\\/\?\*\[\]\:]/g, "-")
        .replace(/\s+/g, " ")
        .substring(0, 50);

      if (!nombreHoja.trim()) nombreHoja = codigoBase;

      var sheet = ss.getSheetByName(nombreHoja);
      if (!sheet && registros.length === 0) {
        sheet = findExistingSheetByCode(ss, codigoBase);
      }

      if (!sheet) {
        if (registros.length === 0) {
          hojasActualizadas.push(codigoBase + "(0 sin hoja previa)");
          continue;
        }
        sheet = ss.insertSheet(nombreHoja);
      }

      var hRange = sheet.getRange(1, 1, 1, NUM_COLS);
      hRange.setValues([headers]);
      hRange.setFontWeight("bold");
      hRange.setBackground("#1a73e8");
      hRange.setFontColor("#ffffff");
      sheet.setFrozenRows(1);

      var lastRow = sheet.getLastRow();
      var colsToClear = Math.max(sheet.getLastColumn(), NUM_COLS);

      if (lastRow >= 2) {
        sheet.getRange(2, 1, lastRow - 1, colsToClear).clearContent();
      }

      var rows = registros.map(function(item) {
        return [
          "'" + (item.almcod || ""),
          item.desc_alm    || "",
          "'" + (item.medcod || ""),
          item.codigo_sig  || "",
          item.xnom        || "",
          "'" + (item.lote || ""),
          item.fecha       || "",
          item.medregsan   || "",
          item.tipsum      || "",
          item.tipsum_des  || "",
          item.ffinan      || "",
          item.ffinan_des  || "",
          item.saldo       || 0,
          item.precio_det  || 0,
          item.preciocab   || 0,
          item.fecha_equipo || item.actualizado || "",
          ultimaActualizacion
        ];
      });

      if (rows.length > 0) {
        sheet.getRange(2, 1, rows.length, NUM_COLS).setValues(rows);
      }

      totalRegistros += rows.length;
      hojasActualizadas.push(nombreHoja + "(" + rows.length + ")");
    }

    var msg = "OK:" + totalRegistros + " registros en hojas: " + hojasActualizadas.join(", ");
    return ContentService.createTextOutput(msg).setMimeType(ContentService.MimeType.TEXT);

  } catch (error) {
    return ContentService
      .createTextOutput("Error: " + error.toString())
      .setMimeType(ContentService.MimeType.TEXT);
  }
}

function resumenPorPuesto() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var hojas = ss.getSheets();

  Logger.log("=== RESUMEN DE ESTABLECIMIENTOS CONECTADOS ===");

  hojas.forEach(function(sheet) {
    var nombre = sheet.getName();
    var lastRow = sheet.getLastRow();

    if (lastRow < 1) return;

    var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    var idxUltima = headers.indexOf("ULTIMA ACTUALIZACION") + 1;

    var registros = Math.max(lastRow - 1, 0);
    var ultimaSync = "";

    if (lastRow >= 2 && idxUltima > 0) {
      ultimaSync = sheet.getRange(2, idxUltima).getValue();
    }

    Logger.log(nombre + " | " + registros + " productos | ultima sync real: " + ultimaSync);
  });
}

function testMultiPuesto() {
  var puestoA = [
    {
      almcod: "06515F0101",
      desc_alm: "FARM - C.S. SAN RAFAEL",
      medcod: "00143",
      codigo_sig: "582400320003",
      xnom: "ACICLOVIR - 200 mg - TABLET -",
      lote: "20203344",
      fecha: "29/02/2028",
      medregsan: "EN04199",
      tipsum: "CN",
      tipsum_des: "SISMED-COMPRA NACIONAL (CN)",
      ffinan: "DYT",
      ffinan_des: "Donaciones y Transferencias (DYT)",
      saldo: 172,
      precio_det: 0.133875,
      preciocab: 0.14875,
      fecha_equipo: "28/05/2026 09:02:00"
    }
  ];

  var puestoB = [
    {
      almcod: "030S0501",
      desc_alm: "ALM SISMED",
      medcod: "00200",
      codigo_sig: "582800250001",
      xnom: "ACIDO FOLICO - 500 ug - TABLET -",
      lote: "2092323",
      fecha: "30/09/2026",
      medregsan: "DN0395",
      tipsum: "CN",
      tipsum_des: "SISMED-COMPRA NACIONAL (CN)",
      ffinan: "DYT",
      ffinan_des: "Donaciones y Transferencias (DYT)",
      saldo: 420,
      precio_det: 0.025875,
      preciocab: 0.02875,
      fecha_equipo: "28/05/2026 09:03:00"
    }
  ];

  var resultA = doPost({ postData: { contents: JSON.stringify(puestoA) } });
  Logger.log("Puesto A: " + resultA.getContent());

  var resultB = doPost({ postData: { contents: JSON.stringify(puestoB) } });
  Logger.log("Puesto B: " + resultB.getContent());
}
