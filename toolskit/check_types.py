import os
from dbfread import DBF

data_dir = r'C:\SISMEDV2\DATOS'
ma_path = os.path.join(data_dir, 'MALMACEN.DBF')
mc_path = os.path.join(data_dir, 'MCATES.DBF')

ma = DBF(ma_path, char_decode_errors='ignore')
print(f"MALMACEN ALMCOD field: {[f for f in ma.fields if f.name == 'ALMCOD'][0]}")

mc = DBF(mc_path, char_decode_errors='ignore')
print(f"MCATES ESTCESTS field: {[f for f in mc.fields if f.name == 'ESTCESTS'][0]}")

# Print first records raw
for r in ma: print(f"MA RAW: {r['ALMCOD']!r}"); break
for r in mc: print(f"MC RAW: {r['ESTCESTS']!r}"); break
