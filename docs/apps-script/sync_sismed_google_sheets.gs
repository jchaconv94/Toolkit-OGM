function normalizeAlmcod(value) {
  return (value || "").toString().replace(/[^0-9A-Za-z]/g, "").toUpperCase();
}

function facilityCodeFromAlmcod(almcod) {
  var code = normalizeAlmcod(almcod);
  if (code.length >= 8 && code.substring(5, 6) === "F") {
    return code.substring(0, 5);
  }
  if (code.length >= 6 && /[A-Z]/.test(code.substring(0, 6))) {
    return code.substring(0, 6);
  }
  return code.length >= 5 ? code.substring(0, 5) : code;
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);

    if (!data || data.length === 0) {
      return ContentService.createTextOutput("OK:0 registros (payload vacio).")
        .setMimeType(ContentService.MimeType.TEXT);
    }

    var headers = [
      "ALMCOD", "DESC_ALM", "ID_Producto", "CODIGO_SIG", "Nombre",
      "Lote", "Fec_Vencim", "Reg_Sanitario",
      "TIPSUM", "DESC_TIPSUM", "FFINAN", "DESC_FFINAN",
      "Saldo", "Precio_Det", "Precio_Cab", "FECHA_DEL_EQUIPO",
      "Ultima_Actualizacion"
    ];
    var NUM_COLS = headers.length;

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var grupos = {};

    data.forEach(function(item) {
      var almFull = normalizeAlmcod(item.almcod || "00000");
      var almBase = facilityCodeFromAlmcod(almFull);
      if (!grupos[almBase]) grupos[almBase] = [];
      grupos[almBase].push(item);
    });

    var totalRegistros = 0;
    var hojasActualizadas = [];

    for (var codigoBase in grupos) {
      var registros = grupos[codigoBase];
      var descAlm = (registros[0].desc_alm || codigoBase).toString().trim();
      descAlm = descAlm.replace(" (CONSOLIDADO)", "");

      var nombreHoja = (descAlm + "-" + codigoBase)
        .replace(/[\\\/\?\*\[\]\:]/g, "-")
        .replace(/\s+/g, " ")
        .substring(0, 50);

      if (!nombreHoja.trim()) nombreHoja = codigoBase;

      var sheet = ss.getSheetByName(nombreHoja);
      if (!sheet) {
        sheet = ss.insertSheet(nombreHoja);
      }

      var hRange = sheet.getRange(1, 1, 1, NUM_COLS);
      hRange.setValues([headers]);
      hRange.setFontWeight("bold");
      hRange.setBackground("#1a73e8");
      hRange.setFontColor("#ffffff");
      sheet.setFrozenRows(1);

      var lastRow = sheet.getLastRow();
      if (lastRow >= 2) {
        sheet.getRange(2, 1, lastRow - 1, NUM_COLS).clearContent();
      }

      var rows = registros.map(function(item) {
        return [
          "'" + (item.almcod || ""),
          item.desc_alm || "",
          "'" + (item.medcod || ""),
          item.codigo_sig || "",
          item.xnom || "",
          "'" + (item.lote || ""),
          item.fecha || "",
          item.medregsan || "",
          item.tipsum || "",
          item.tipsum_des || "",
          item.ffinan || "",
          item.ffinan_des || "",
          item.saldo || 0,
          item.precio_det || 0,
          item.preciocab || 0,
          item.fecha_equipo || item.actualizado || "",
          Utilities.formatDate(new Date(), "America/Lima", "dd/MM/yyyy HH:mm:ss")
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
