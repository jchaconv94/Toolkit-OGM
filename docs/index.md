import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.38.4";

async function hashToken(token: string) {
  const messageBuffer = new TextEncoder().encode(token);
  const hashBuffer = await crypto.subtle.digest("SHA-256", messageBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

function normalizeCode(value: string | null | undefined) {
  return (value || '').toString().replace(/[^0-9A-Za-z]/g, '').toUpperCase();
}

function facilityCodeFromAlmcod(almcod: string) {
  const code = normalizeCode(almcod);
  if (code.length >= 8 && code.substring(5, 6) === 'F') {
    return code.substring(0, 5);
  }
  if (code.length >= 6 && /[A-Z]/.test(code.substring(0, 6))) {
    return code.substring(0, 6);
  }
  return code.length >= 5 ? code.substring(0, 5) : code;
}

function normalizeAlmcodList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => normalizeCode(String(item))).filter(Boolean);
}

serve(async (req) => {
  // Configurar CORS para permitir que clientes e invocaciones externas operen
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, x-installation-token, x-toolkit-version',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
  };

  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Metodo no permitido. Use POST.' }), {
      status: 405,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  try {
    // 1. Leer el token desde Authorization Bearer o el header especial X-Installation-Token
    let token = req.headers.get('x-installation-token');
    const authHeader = req.headers.get('authorization');
    if (!token && authHeader && authHeader.toLowerCase().startsWith('bearer ')) {
      token = authHeader.substring(7);
    }

    if (!token) {
      return new Response(JSON.stringify({ error: 'Token de instalación no proporcionado' }), {
        status: 401,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    const payload = await req.json();
    const {
      mode,
      record_count,
      records,
      toolkit_version,
      fecha_equipo,
      reported_almcods,
      omit_zero_stock,
      sismed_path,
    } = payload;

    // Validar que los records sean un array y que coincida el record_count reportado
    if (!Array.isArray(records)) {
      return new Response(JSON.stringify({ error: 'Error de validación: records debe ser un arreglo' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    if (records.length !== record_count) {
      return new Response(JSON.stringify({ error: 'Error de validación: record_count no coincide con la longitud real de records' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // 2. Inicializar cliente Supabase usando la Service Role Key para puentear RLS e insertar la ingesta
    const supabaseUrl = Deno.env.get('SUPABASE_URL') || '';
    const supabaseServiceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '';

    if (!supabaseUrl || !supabaseServiceKey) {
       return new Response(JSON.stringify({ error: 'Configuración del servidor incompleta (Variables de entorno requeridas)' }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    // 3. Hashear el token de la petición y buscar su equivalente almacenado en public.sync_installations
    const hashedToken = await hashToken(token);
    
    const { data: installation, error: instError } = await supabase
      .from('sync_installations')
      .select('*')
      .eq('token_hash', hashedToken)
      .single();

    // Validar existencia de la instancia autorizada
    if (instError || !installation) {
      return new Response(JSON.stringify({ error: 'Instalación no válida o no encontrada con el token proporcionado' }), {
        status: 401,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    if (!installation.is_active) {
      return new Response(JSON.stringify({ error: 'Instalación inactiva: Póngase en contacto con su administrador' }), {
        status: 403,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // 4. Inferir instalación y extraer reglas de permitidos
    const facilityCode = normalizeCode(installation.facility_code);
    const allowedAlmcods = (installation.allowed_almcods || []).map((code: string) => normalizeCode(code));

    if (!facilityCode) {
      return new Response(JSON.stringify({ error: 'Instalación inválida: no tiene facility_code autorizado.' }), {
        status: 403,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    const auditSecurityBlock = async (
      reason: string,
      detectedAlmcods: string[],
      rejectedAlmcods: any[],
      message: string,
    ) => {
      try {
        await supabase
          .from('sync_runs')
          .insert({
            installation_id: installation.id,
            facility_code: facilityCode,
            mode: mode || 'detallado',
            record_count: Array.isArray(records) ? records.length : 0,
            fecha_equipo: fecha_equipo,
            status: 'failed',
            error_message: JSON.stringify({
              security_event: reason,
              message,
              authorized_facility_code: facilityCode,
              detected_almcods: detectedAlmcods,
              rejected_almcods: rejectedAlmcods,
              sismed_path: sismed_path || null,
              toolkit_version: toolkit_version || null,
              blocked_at: new Date().toISOString(),
            }).substring(0, 4000),
            finished_at: new Date().toISOString(),
          });
      } catch (auditError: any) {
        console.error('No se pudo registrar auditoría de bloqueo:', auditError.message);
      }
    };

    const incomingAlmcods = new Set<string>();
    for (const reportedAlmcod of normalizeAlmcodList(reported_almcods)) {
      incomingAlmcods.add(reportedAlmcod);
    }

    let cleanedRecords = [];
    
    // Validar, formatear e inyectar el facility_code forzado en los registros entrantes
    for (const record of records) {
      const recAlmcod = normalizeCode(record.almcod);
      if (!recAlmcod) continue;
      
      incomingAlmcods.add(recAlmcod);

      if (omit_zero_stock && Number(record.saldo || 0) === 0) {
        continue;
      }
      
      cleanedRecords.push({
        facility_code: facilityCode || facilityCodeFromAlmcod(recAlmcod),
        almcod: recAlmcod,
        desc_alm: record.desc_alm,
        medcod: record.medcod,
        codigo_sig: record.codigo_sig,
        xnom: record.xnom,
        lote: record.lote,
        fecha: record.fecha,
        medregsan: record.medregsan,
        tipsum: record.tipsum,
        tipsum_des: record.tipsum_des,
        ffinan: record.ffinan,
        ffinan_des: record.ffinan_des,
        saldo: record.saldo,
        precio_det: record.precio_det,
        preciocab: record.preciocab,
        fecha_equipo: record.fecha_equipo || fecha_equipo,
        // ultima_actualizacion será injectado por PostgreSQL automatically a través de su default gen_random_uuid / now()
      });
    }

    // 5. Hard-stop si un almcod provisto no está en la lista blanca de esta instalación (para evitar manipulación de stock foráneo)
    const dedupedRecordsMap = new Map<string, any>();
    for (const record of cleanedRecords) {
      const recordKey = [
        record.facility_code,
        record.almcod,
        record.medcod,
        record.lote,
        record.fecha,
        record.ffinan,
        record.tipsum,
      ].join('|');
      const existing = dedupedRecordsMap.get(recordKey);
      if (existing) {
        existing.saldo = Number(existing.saldo || 0) + Number(record.saldo || 0);
        existing.precio_det = Math.max(Number(existing.precio_det || 0), Number(record.precio_det || 0));
        existing.preciocab = Math.max(Number(existing.preciocab || 0), Number(record.preciocab || 0));
      } else {
        dedupedRecordsMap.set(recordKey, record);
      }
    }
    cleanedRecords = Array.from(dedupedRecordsMap.values());

    const incomingAlmcodList = Array.from(incomingAlmcods).sort();
    const rejectedByFacility = [];

    for (const almcod of incomingAlmcodList) {
      const detectedFacilityCode = facilityCodeFromAlmcod(almcod);
      if (detectedFacilityCode && detectedFacilityCode !== facilityCode) {
        rejectedByFacility.push({
          almcod,
          detected_facility_code: detectedFacilityCode,
          authorized_facility_code: facilityCode,
        });
      }
    }

    if (rejectedByFacility.length > 0) {
      const firstRejected = rejectedByFacility[0];
      const message = `Violación de seguridad: ALMCOD ${firstRejected.almcod} pertenece a ${firstRejected.detected_facility_code}, pero esta instalación está autorizada para ${facilityCode}.`;
      await auditSecurityBlock(
        'almcod_facility_mismatch',
        incomingAlmcodList,
        rejectedByFacility,
        message,
      );
      return new Response(JSON.stringify({
        error: message,
        rejected_almcods: rejectedByFacility,
      }), {
        status: 403,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    if (allowedAlmcods.length > 0) {
      for (const almcod of incomingAlmcodList) {
        if (!allowedAlmcods.includes(almcod)) {
          const message = `Violación de seguridad: ALMCOD ${almcod} no está permitido para esta instalación del Toolkit.`;
          await auditSecurityBlock(
            'almcod_not_whitelisted',
            incomingAlmcodList,
            [{ almcod, authorized_facility_code: facilityCode }],
            message,
          );
          return new Response(JSON.stringify({ error: message }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
    }

    // 6. Crear un registro de ejecución/auditoría bajo 'sync_runs' marcándolo como processing
    const { data: syncRun, error: runError } = await supabase
      .from('sync_runs')
      .insert({
        installation_id: installation.id,
        facility_code: facilityCode,
        mode: mode || 'consolidado',
        record_count: cleanedRecords.length,
        fecha_equipo: fecha_equipo,
        status: 'processing'
      })
      .select()
      .single();

    if (runError) {
      throw new Error(`Error creando auditoria sync_run: ${runError.message}`);
    }

    try {
      // 7. Flujo de reemplazo completo (Delete + Insert): 
      // Se borra el target completo del servidor para asegurar que los items que dejaron de existir o llegaron a cero y desaparecieron de los dbf locales también salgan del cloud.
      if (incomingAlmcodList.length > 0) {
        const { error: delError } = await supabase
          .from('stock_actual')
          .delete()
          .eq('facility_code', facilityCode)
          .in('almcod', incomingAlmcodList);
          
        if (delError) {
           throw new Error(`Restricción borrando stock previo: ${delError.message}`);
        }
      }

      // 8. Inserción segmentada (Optimización en chunks para saltar limite de bytes en petición RPC a sudbabase)
      if (cleanedRecords.length > 0) {
          const chunkSize = 1000;
          for (let i = 0; i < cleanedRecords.length; i += chunkSize) {
            const chunk = cleanedRecords.slice(i, i + chunkSize);
            const { error: insError } = await supabase.from('stock_actual').insert(chunk);
            if (insError) throw new Error(`Restricción insertando batch nuevos datos: ${insError.message}`);
          }
      }

      // 9. Marcar ejecución en verde indicando hora final y exito
      await supabase
        .from('sync_runs')
        .update({ status: 'success', finished_at: new Date().toISOString() })
        .eq('id', syncRun.id);

      // 10. Actualizar heartbeat (ping) de la instancia para dashboards web de administración
      await supabase
        .from('sync_installations')
        .update({ 
          last_seen_at: new Date().toISOString(),
          toolkit_version: toolkit_version || installation.toolkit_version
        })
        .eq('id', installation.id);

      // 11. Conclusión y envío respuesta final al Toolkit de que los datos acaban de subir a producción
      return new Response(JSON.stringify({ 
        success: true, 
        sync_run_id: syncRun.id, 
        records: cleanedRecords.length 
      }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });

    } catch (processError: any) {
      // De fallar el SQL intermedio, re-marcamos el logger a fallido con su causa
      await supabase
        .from('sync_runs')
        .update({ 
           status: 'failed', 
           error_message: processError.message,
           finished_at: new Date().toISOString() 
        })
        .eq('id', syncRun.id);
        
      throw processError; // Escalar el throw al manejador HTTP central
    }

  } catch (error: any) {
    console.error('Error Crítico procesando edge function sync-stock:', error.message);
    return new Response(JSON.stringify({ error: 'Error Interno del Servidor procesando los reportes SISMED DBF.', details: error.message }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }
});
