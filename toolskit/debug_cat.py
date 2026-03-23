import os
from dbfread import DBF

data_dir = r'C:\SISMEDV2\DATOS'
ma_path = os.path.join(data_dir, 'MALMACEN.DBF')
mc_path = os.path.join(data_dir, 'MCATES.DBF')

cates = {}
for rec in DBF(mc_path, char_decode_errors='ignore'):
    cod = str(rec['ESTCESTS']).strip()
    cat = str(rec['ESTCCAT']).strip()
    cates[cod] = cat

print(f"Loaded {len(cates)} from MCATES")

for rec in DBF(ma_path, char_decode_errors='ignore'):
    cod = str(rec['ALMCOD']).strip()
    if cod == '06499':
        des = str(rec['ALMDES']).strip()
        cat = cates.get(cod, "NOT FOUND IN MCATES")
        print(f"ALMCOD: {cod}, DES: {des}, CATEG: {cat}")
