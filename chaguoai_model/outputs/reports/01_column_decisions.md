# Column Decisions

| Column | Decision | Reason |
|--------|----------|--------|
| visitid | KEEP | Used in modelling or needed for target variable |
| serialnumber | DROP | Facility admin ID — no predictive signal |
| uniqueid | KEEP | Used in modelling or needed for target variable |
| organization | KEEP | Used in modelling or needed for target variable |
| county | KEEP | Used in modelling or needed for target variable |
| division | DROP | 23 divisions — too granular; county is sufficient |
| year | KEEP | Used in modelling or needed for target variable |
| month | KEEP | Used in modelling or needed for target variable |
| delivery | KEEP | Used in modelling or needed for target variable |
| delivery_channel | DROP | 2-bucket collapse of delivery — redundant |
| facilityname | DROP | 84.3% missing — unusable |
| gender | KEEP | Used in modelling or needed for target variable |
| age | KEEP | Used in modelling or needed for target variable |
| client_age | DROP | Bucketed age — redundant with numeric age column |
| educationlevel | KEEP | Used in modelling or needed for target variable |
| noofchildren | KEEP | Used in modelling or needed for target variable |
| no_children | DROP | Bucketed parity — redundant with noofchildren |
| fertilityintention | KEEP | Used in modelling or needed for target variable |
| fpstatus | KEEP | Used in modelling or needed for target variable |
| projectstatus | DROP | Same as fpstatus — redundant |
| projectfpstatus | DROP | Mixes FP status with project status — not needed |
| previousmethod | KEEP | Used in modelling or needed for target variable |
| prev_fp | DROP | 3-bucket collapse of previousmethod — we derive own categories |
| counseled | KEEP | Used in modelling or needed for target variable |
| new_counselled | DROP | Binary collapse of counseled — redundant |
| methodadopted | KEEP | Used in modelling or needed for target variable |
| fp_adopted | DROP | 3-bucket collapse of methodadopted — we derive own categories |
| referred | DROP | 71.6% missing — unusable |
| fp_referred | DROP | 73.2% missing — unusable |
| pillquantity | DROP | 76.3% missing — unusable |
| condomquantity | DROP | 58.2% missing — unusable |
| lapm | DROP | Derivable from methodadopted — redundant |
| client_age2 | DROP | Second bucketed age — redundant |