/**
 * Recepción del stock que envía Sync SISMED (ToolKit SISMED de escritorio).
 *
 * Cada establecimiento envía su inventario completo y aquí se escribe en la pestaña que le
 * corresponde, reemplazando lo anterior.
 *
 * Versión 3 — cambios respecto a la original:
 *
 *  1. La pestaña NUNCA queda vacía ni a medias. Antes se borraba todo y después se escribía;
 *     si Google fallaba entre los dos pasos, el establecimiento quedaba sin stock hasta el
 *     siguiente envío. Ahora el reemplazo es una sola escritura: el stock nuevo más filas en
 *     blanco donde sobraba el anterior. O entra completo, o queda el que había.
 *  2. Un envío a la vez. Con varias PC enviando al mismo libro, las escrituras se pisaban y
 *     Google respondía con errores de tiempo agotado. Ahora esperan su turno (candado).
 *  3. Hojas de más de 999 lotes. Si la pestaña no tiene filas suficientes, se agregan antes
 *     de escribir.
 *  4. Menos trabajo por envío. El encabezado y su formato se escriben solo al crear la
 *     pestaña (o si alguien los cambió), no en cada envío: cinco escrituras menos por vez.
 *  5. Nombres largos. El nombre de la pestaña se cortaba a 50 caracteres y, con una
 *     descripción de más de 44, se perdía el «-código» del final. Desde el segundo envío el
 *     script ya no reconocía esa pestaña, intentaba crearla otra vez, Google respondía «ya
 *     existe» y el establecimiento no volvía a actualizarse. Ahora se recorta la descripción
 *     y el código se conserva siempre; las pestañas que quedaron con el nombre cortado se
 *     reconocen y vuelven a actualizarse solas.
 *
 *  6. Establecimientos con clave de envío (versión 3). Las claves se gestionan en
 *     ToolkitSISMED Web. Antes de escribir la pestaña de un establecimiento con clave, el
 *     script pregunta a la web si la clave y la PC que vienen en el envío son las vigentes;
 *     si no lo son, la pestaña no se toca y la respuesta lo dice («BLOQUEADO: código=motivo»).
 *     Así ni un Toolkit antiguo ni un envío hecho a mano a esta dirección pueden reemplazar
 *     ese stock. Los establecimientos sin clave envían como siempre.
 *     Si la web no responde, el envío pasa como siempre: una caída de la web no deja a
 *     nadie sin actualizar.
 *     No hay nada que configurar: basta con pegar este código y publicar una versión nueva.
 *
 * Lo que NO cambia: el formato de las filas, los nombres de las pestañas y la respuesta
 * («OK:<n> registros...» / «Error: ...»), que es lo que leen el escritorio y la web.
 */

var HEADERS = [
  "ALMCOD", "DESC_ALM", "ID_Producto", "CODIGO_SIG", "Nombre",
  "Lote", "Fec_Vencim", "Reg_Sanitario",
  "TIPSUM", "DESC_TIPSUM", "FFINAN", "DESC_FFINAN",
  "Saldo", "Precio_Det", "Precio_Cab",
  "FECHA DEL EQUIPO", "ULTIMA ACTUALIZACION"
];
var NUM_COLS = HEADERS.length;

/**
 * ToolkitSISMED Web, donde viven las claves de envío. La clave es la pública («publishable»),
 * la misma que ya usa la página web: no da acceso a nada que no sea público.
 */
var WEB_URL = "https://ujknopysvgqqvkmgrfhp.supabase.co";
var WEB_CLAVE_PUBLICA = "__CLAVE_PUBLICA__";
/** Cuánto se recuerda que un establecimiento NO tiene clave, para no preguntar en cada envío. */
var SIN_CLAVE_CACHE_SEGUNDOS = 300;

/** Cuánto espera un envío a que termine el anterior antes de rendirse (ms). */
var ESPERA_CANDADO_MS = 30000;

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

function isSheetForCode(name, codigoBase) {
  var suffix = "-" + codigoBase;
  return name === codigoBase || name.slice(-suffix.length) === suffix;
}

function isGenericSheetName(name, codigoBase) {
  var suffix = "-" + codigoBase;
  var baseName = name === codigoBase ? name : name.slice(0, -suffix.length);
  var upper = baseName
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();

  var genericNames = [
    "ALM SISMED",
    "FAR SISMED",
    "FARM SISMED",
    "FAR DONACIONES",
    "FARMACIA SISMED"
  ];

  for (var i = 0; i < genericNames.length; i++) {
    if (upper === genericNames[i] || upper.indexOf(genericNames[i]) >= 0) {
      return true;
    }
  }

  return false;
}

/**
 * Pestaña existente para un código. Recibe la lista de pestañas ya leída, para no pedírsela
 * a Google una vez por cada establecimiento del envío.
 */
function findExistingSheetByCode(sheets, codigoBase, generatedName) {
  var exact = null;
  var firstMatch = null;
  var firstNonGeneric = null;

  for (var i = 0; i < sheets.length; i++) {
    var name = sheets[i].getName();
    if (!isSheetForCode(name, codigoBase)) {
      continue;
    }

    if (!firstMatch) {
      firstMatch = sheets[i];
    }

    if (name === generatedName) {
      exact = sheets[i];
    }

    if (!firstNonGeneric && !isGenericSheetName(name, codigoBase)) {
      firstNonGeneric = sheets[i];
    }
  }

  // Si ya existe una hoja con el mismo codigo IPRESS y un nombre mas descriptivo,
  // se reutiliza para evitar duplicados como "ALM SISMED-030S05".
  return firstNonGeneric || exact || firstMatch;
}

function texto_(mensaje) {
  return ContentService.createTextOutput(mensaje).setMimeType(ContentService.MimeType.TEXT);
}

/** Filas de un registro. Idénticas a la versión anterior: la web las lee así. */
function filaDeRegistro_(item, ultimaActualizacion) {
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
}

var LARGO_MAXIMO_NOMBRE = 50;

function descripcionDeHoja_(registros, codigoBase) {
  return (registros.length > 0 ? (registros[0].desc_alm || codigoBase) : codigoBase)
    .toString()
    .trim()
    .replace(" (CONSOLIDADO)", "")
    .replace(/[\\\/\?\*\[\]\:]/g, "-")
    .replace(/\s+/g, " ");
}

/**
 * Nombre de una pestaña nueva: la descripción, recortada si hace falta, y el código al
 * final SIEMPRE. El código es lo que permite reconocerla en los envíos siguientes.
 */
function nombreDeHoja_(registros, codigoBase) {
  var sufijo = "-" + codigoBase;
  var descripcion = descripcionDeHoja_(registros, codigoBase)
    .substring(0, LARGO_MAXIMO_NOMBRE - sufijo.length)
    .trim();
  return descripcion ? descripcion + sufijo : codigoBase;
}

/**
 * Nombre que le habría puesto la versión anterior, que cortaba el nombre completo y podía
 * dejar la pestaña sin su código. Solo sirve para reconocer esas pestañas y seguir
 * actualizándolas. Si el nombre no llegaba a cortarse, coincide con el nuevo y no hace falta.
 */
function nombreDeHojaAnterior_(registros, codigoBase) {
  var nombre = (descripcionDeHoja_(registros, codigoBase) + "-" + codigoBase)
    .substring(0, LARGO_MAXIMO_NOMBRE);
  return nombre.trim() ? nombre : codigoBase;
}

/**
 * Pestaña que la versión anterior dejó con el nombre cortado. Antes de adoptarla se
 * comprueba que su primera fila sea del mismo establecimiento: dos establecimientos con la
 * misma descripción larga dan el mismo nombre cortado, y escribir en la pestaña del otro
 * sería reemplazarle el stock.
 */
function buscarHojaConNombreCortado_(hojas, nombreAnterior, codigoBase) {
  for (var i = 0; i < hojas.length; i++) {
    if (hojas[i].getName() !== nombreAnterior) continue;
    var almcod = hojas[i].getRange(2, 1).getValues()[0][0];
    var codigo = facilityCodeFromAlmcod(normalizeAlmcod(almcod));
    return !codigo || codigo === codigoBase ? hojas[i] : null;
  }
  return null;
}

function aplicarEncabezado_(sheet) {
  var rango = sheet.getRange(1, 1, 1, NUM_COLS);
  rango.setValues([HEADERS]);
  rango.setFontWeight("bold");
  rango.setBackground("#1a73e8");
  rango.setFontColor("#ffffff");
  sheet.setFrozenRows(1);
}

/**
 * El encabezado se reescribe solo si falta o alguien lo cambió. Es una lectura en vez de
 * cinco escrituras, y en casi todos los envíos no hace falta tocarlo.
 */
function asegurarEncabezado_(sheet) {
  var actual = sheet.getRange(1, 1, 1, NUM_COLS).getValues()[0];
  for (var i = 0; i < NUM_COLS; i++) {
    if (String(actual[i]) !== HEADERS[i]) {
      aplicarEncabezado_(sheet);
      return;
    }
  }
}

/**
 * Reemplaza el stock de una pestaña en UNA sola escritura: el stock nuevo y, debajo, filas
 * en blanco hasta donde llegaba el envío anterior. Así no existe ningún momento en que la
 * pestaña esté vacía ni mezclando lotes nuevos con viejos: o entra el envío completo, o
 * queda el que había.
 */
function escribirStock_(sheet, filas) {
  var filasAnteriores = Math.max(sheet.getLastRow() - 1, 0);
  var ultimaColumna = sheet.getLastColumn();
  var alto = Math.max(filas.length, filasAnteriores);
  if (alto === 0) return;

  var maxFilas = sheet.getMaxRows();
  if (maxFilas < alto + 1) {
    sheet.insertRowsAfter(maxFilas, alto + 1 - maxFilas);
  }

  var bloque = filas.slice();
  var filaVacia = [];
  for (var c = 0; c < NUM_COLS; c++) filaVacia.push("");
  while (bloque.length < alto) bloque.push(filaVacia);

  sheet.getRange(2, 1, alto, NUM_COLS).setValues(bloque);

  // Columnas a la derecha de las 17 (de versiones antiguas o escritas a mano): la versión
  // anterior las borraba al vaciar la hoja completa, y se mantiene ese comportamiento.
  if (ultimaColumna > NUM_COLS) {
    sheet.getRange(2, NUM_COLS + 1, alto, ultimaColumna - NUM_COLS).clearContent();
  }
}

function doPost(e) {
  // --- 1. Leer y validar el envío (sin tocar la hoja todavía) ---
  var data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return texto_("Error: el envío no es un JSON válido.");
  }
  if (!Array.isArray(data)) {
    return texto_("Error: se esperaba una lista de registros.");
  }

  var reportedAlmcods = splitReportedAlmcods(
    e && e.parameter ? e.parameter.reported_almcods : ""
  );

  if (data.length === 0 && reportedAlmcods.length === 0) {
    return texto_("OK:0 registros (payload vacio).");
  }

  var ultimaActualizacion = Utilities.formatDate(
    new Date(),
    "America/Lima",
    "dd/MM/yyyy HH:mm:ss"
  );

  // --- 2. Armar las filas en memoria, fuera del candado: no hace esperar a nadie ---
  var grupos = {};
  data.forEach(function(item) {
    var alm_base = facilityCodeFromAlmcod(normalizeAlmcod(item.almcod || "00000"));
    if (!grupos[alm_base]) grupos[alm_base] = [];
    grupos[alm_base].push(item);
  });

  // Un ALMCOD reportado sin registros significa «ya no tiene stock»: su pestaña se vacía.
  reportedAlmcods.forEach(function(almcod) {
    var alm_base = facilityCodeFromAlmcod(almcod);
    if (alm_base && !grupos[alm_base]) grupos[alm_base] = [];
  });

  // --- Establecimientos con clave: solo los escribe un Toolkit que verificó la clave ---
  var parametros = (e && e.parameter) || {};
  var rechazados = filtrarConClave_(grupos, parametros);

  var trabajos = [];
  for (var codigoBase in grupos) {
    var registros = grupos[codigoBase];
    trabajos.push({
      codigoBase: codigoBase,
      nombreHoja: nombreDeHoja_(registros, codigoBase),
      nombreAnterior: nombreDeHojaAnterior_(registros, codigoBase),
      filas: registros.map(function(item) { return filaDeRegistro_(item, ultimaActualizacion); })
    });
  }

  // --- 3. Escribir, un envío a la vez ---
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(ESPERA_CANDADO_MS)) {
    return texto_("Error: la hoja está ocupada con otro envío. Se reintentará en el próximo ciclo.");
  }

  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var hojas = ss.getSheets();
    var totalRegistros = 0;
    var hojasActualizadas = [];

    for (var i = 0; i < trabajos.length; i++) {
      var t = trabajos[i];
      var sheet = findExistingSheetByCode(hojas, t.codigoBase, t.nombreHoja);
      if (!sheet && t.nombreAnterior !== t.nombreHoja) {
        sheet = buscarHojaConNombreCortado_(hojas, t.nombreAnterior, t.codigoBase);
      }

      if (!sheet) {
        if (t.filas.length === 0) {
          hojasActualizadas.push(t.codigoBase + "(0 sin hoja previa)");
          continue;
        }
        sheet = ss.insertSheet(t.nombreHoja);
        hojas.push(sheet);
        aplicarEncabezado_(sheet);
      } else {
        asegurarEncabezado_(sheet);
      }

      escribirStock_(sheet, t.filas);

      totalRegistros += t.filas.length;
      hojasActualizadas.push(sheet.getName() + "(" + t.filas.length + ")");
    }

    // Que todo quede guardado antes de soltar el turno al siguiente envío.
    SpreadsheetApp.flush();

    var respuesta = "OK:" + totalRegistros + " registros en hojas: " + hojasActualizadas.join(", ");
    if (rechazados.length) {
      respuesta += " | BLOQUEADO: " + rechazados.join(",");
    }
    return texto_(respuesta);
  } catch (error) {
    return texto_("Error: " + error.toString());
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------------------
//  Protección de los establecimientos con clave de envío
// ---------------------------------------------------------------------------

/** La clave de cada código es la que empieza con «código-». Pueden venir varias. */
function clavesPorCodigo_(valor) {
  var mapa = {};
  String(valor || "").split(/[\s,;]+/).forEach(function(clave) {
    clave = clave.replace(/\s/g, "").toUpperCase();
    var codigo = clave.split("-")[0];
    if (codigo) mapa[codigo] = clave;
  });
  return mapa;
}

/**
 * Quita del envío los establecimientos con clave cuya clave o PC no son las vigentes, y
 * devuelve «código=motivo» de cada uno. Una sola consulta a la web por envío; los códigos
 * que ya se sabe que no tienen clave ni siquiera se consultan durante unos minutos.
 * Si la web no responde, no se quita nada.
 */
function filtrarConClave_(grupos, parametros) {
  var codigos = Object.keys(grupos);
  if (!codigos.length || !WEB_CLAVE_PUBLICA || WEB_CLAVE_PUBLICA.indexOf("__") === 0) return [];

  var cache = CacheService.getScriptCache();
  var sinClave = cache.getAll(codigos.map(function(c) { return "sinclave:" + c; }));
  var porConsultar = codigos.filter(function(c) { return !sinClave["sinclave:" + c]; });
  if (!porConsultar.length) return [];

  var claves = clavesPorCodigo_(parametros.clave);
  var respuesta;
  try {
    var http = UrlFetchApp.fetch(WEB_URL + "/rest/v1/rpc/app_send_key_verify", {
      method: "post",
      contentType: "application/json",
      headers: { apikey: WEB_CLAVE_PUBLICA },
      payload: JSON.stringify({
        p_items: porConsultar.map(function(c) { return { code: c, key: claves[c] || "" }; }),
        p_device_id: String(parametros.equipo_id || "")
      }),
      muteHttpExceptions: true
    });
    if (http.getResponseCode() !== 200) throw new Error("HTTP " + http.getResponseCode());
    respuesta = JSON.parse(http.getContentText());
  } catch (err) {
    console.warn("No se pudo verificar la clave de envío; el envío pasa como siempre: " + err);
    return [];
  }

  var rechazados = [];
  var nuevosSinClave = {};
  porConsultar.forEach(function(codigo) {
    var r = respuesta && respuesta[codigo];
    if (!r || !r.protegido) {
      nuevosSinClave["sinclave:" + codigo] = "1";
      return;
    }
    if (!r.permitido) {
      delete grupos[codigo];
      rechazados.push(codigo + "=" + (r.motivo || "OTRO_EQUIPO"));
    }
  });
  if (Object.keys(nuevosSinClave).length) cache.putAll(nuevosSinClave, SIN_CLAVE_CACHE_SEGUNDOS);
  return rechazados;
}

/** Ejecutar desde el editor, solo como consulta: comprueba que el script llega a la web. */
function probarConexionConLaWeb() {
  var http = UrlFetchApp.fetch(WEB_URL + "/rest/v1/rpc/app_send_key_verify", {
    method: "post", contentType: "application/json", headers: { apikey: WEB_CLAVE_PUBLICA },
    payload: JSON.stringify({ p_items: [], p_device_id: "" }), muteHttpExceptions: true
  });
  Logger.log(http.getResponseCode() === 200 ? "Conexión con la web correcta." : "La web respondió " + http.getResponseCode() + ": " + http.getContentText());
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

/**
 * Prueba manual. Usa códigos que no existen (99999 y 999S99) a propósito: la versión
 * anterior usaba 06515 y 030S05, y como cada envío REEMPLAZA el stock de la pestaña,
 * ejecutarla en la hoja real borraba el stock verdadero de esos dos establecimientos.
 * Crea dos pestañas de prueba que se pueden eliminar después.
 */
function testMultiPuesto() {
  var puestoA = [
    {
      almcod: "99999F0101",
      desc_alm: "PRUEBA - PUESTO A",
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
      almcod: "999S9901",
      desc_alm: "PRUEBA - ALMACEN B",
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
