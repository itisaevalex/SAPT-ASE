import json
import re

# PASTE THE MULTI-LINE STRING OF MISSING DIMERS AND BASES HERE
missing_data_text = """
DIMERS with at least one basis absent:
04_ammonia_dimer                →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
02_adenine_thymine_stack        →  aug-cc-pVQZ, def2-QZVPD
03_adenine_thymine_watsoncrick  →  jun-cc-pVTZ, aug-cc-pVTZ, jun-cc-pVQZ, aug-cc-pVQZ, def2-SVPD, def2-TZVPD, def2-TZVPPD, def2-QZVPD
05_benzene_methane              →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
06_benzene_ammonia              →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
07_benzene_dimer_parallel       →  jun-cc-pVQZ, aug-cc-pVQZ, def2-SVPD, def2-QZVPD
08_benzene_dimer_tshape         →  jun-cc-pVDZ, aug-cc-pVDZ, jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
09_benzene_hcn                  →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
10_benzene_water                →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
11_ethene_dimer                 →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
12_ethene_ethyne                →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
13_formamide_dimer              →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
14_formic_acid_dimer            →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
15_indole_benzene_stack         →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
16_indole_benzene_tshape        →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
17_methane_dimer                →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
18_phenol_dimer                 →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
19_pyrazine_dimer               →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
20_uracil_dimer_hbonded         →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
21_uracil_dimer_stack           →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
22_water_dimer                  →  jun-cc-pVQZ, aug-cc-pVQZ, def2-QZVPD
"""

pairs = []
for line in missing_data_text.strip().splitlines():
    if '→' not in line:
        continue
    # Use regex to better handle potential extra spaces around dimer name
    match_dimer = re.match(r"([0-9A-Za-z_.-]+)\s*→", line)
    if not match_dimer:
        print(f"Skipping malformed line (dimer name): {line}")
        continue
    dimer = match_dimer.group(1).strip()
    
    bases_part = line.split('→', 1)[1]
    for b in bases_part.split(','):
        pairs.append((dimer, b.strip()))

output_filename = "missing_pairs.json" # Will be created in the CWD (Code/)
with open(output_filename, "w") as fh:
    json.dump(pairs, fh, indent=2)

print(f"Successfully wrote {len(pairs)} dimer-basis pairs to {output_filename}")
