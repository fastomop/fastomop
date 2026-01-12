# OMOP CDM Knowledge Base - Consolidated

## How to Use

1. Get `query_category` from SemanticContext
2. Find the matching category section below
3. Use the template EXACTLY as written
4. Substitute placeholders with values from context

---

## Hierarchy Patterns

### Drug Hierarchy (3-step)

```sql
drug{N}_source AS (
  SELECT concept_id FROM {schema}.concept
  WHERE vocabulary_id = 'RxNorm' AND concept_code = '{code}' AND invalid_reason IS NULL
),
drug{N}_mapped AS (
  SELECT concept_id_2 AS concept_id
  FROM drug{N}_source ds
  JOIN {schema}.concept_relationship cr ON ds.concept_id = cr.concept_id_1
  WHERE cr.relationship_id = 'Maps to'
),
drug{N}_concepts AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM drug{N}_mapped dm
  JOIN {schema}.concept c ON dm.concept_id = c.concept_id
  JOIN {schema}.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
```

### Condition Hierarchy (3-step with domain filter)

```sql
seed_{N} AS (
  SELECT c.concept_id AS src_id FROM {schema}.concept c
  WHERE c.vocabulary_id = 'SNOMED' AND c.concept_code = '{code}' AND c.invalid_reason IS NULL
),
std_{N} AS (
  SELECT DISTINCT COALESCE(cr.concept_id_2, s.src_id) AS standard_id
  FROM seed_{N} s
  LEFT JOIN {schema}.concept_relationship cr ON cr.concept_id_1 = s.src_id 
    AND cr.relationship_id = 'Maps to' AND cr.invalid_reason IS NULL
),
desc_{N} AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM std_{N} sa
  JOIN {schema}.concept_ancestor ca ON ca.ancestor_concept_id = sa.standard_id
  JOIN {schema}.concept c ON c.concept_id = ca.descendant_concept_id
  WHERE c.standard_concept = 'S' AND c.domain_id = 'Condition' AND c.invalid_reason IS NULL
)
```

---

## Category: BIRTH_YEAR

**Query:** "Number of patients born in year YYYY"

```sql
SELECT COUNT(DISTINCT person_id) AS patient_count
FROM {schema}.person
WHERE year_of_birth = {year};
```

**⚠️ Use `year_of_birth` directly. Do NOT use `EXTRACT(YEAR FROM birth_datetime)`.**

---

## Category: DEMOGRAPHIC

**Query:** "Patients grouped by gender/race/ethnicity"

**Instructions:** Build CTEs for each demographic field in `additional_filters.group_by`. Use the pattern below and adapt based on which fields are requested.

**Example 1: Gender + Ethnicity**
```sql
WITH gen_concepts AS (
  SELECT concept_id, concept_name AS gender
  FROM {schema}.concept WHERE domain_id = 'Gender' AND standard_concept = 'S'
),
eth_concepts AS (
  SELECT concept_id, concept_name AS ethnicity
  FROM {schema}.concept WHERE domain_id = 'Ethnicity' AND standard_concept = 'S'
)
SELECT
  COALESCE(gc.gender, 'Unknown') AS gender,
  COALESCE(ec.ethnicity, 'Unknown') AS ethnicity,
  COUNT(DISTINCT p.person_id) AS patient_count
FROM {schema}.person p
LEFT JOIN gen_concepts gc ON p.gender_concept_id = gc.concept_id
LEFT JOIN eth_concepts ec ON p.ethnicity_concept_id = ec.concept_id
GROUP BY gc.gender, ec.ethnicity;
```

**Example 2: Race only**
```sql
WITH race_concepts AS (
  SELECT concept_id, concept_name AS race
  FROM {schema}.concept WHERE domain_id = 'Race' AND standard_concept = 'S'
)
SELECT
  COALESCE(rc.race, 'Unknown') AS race,
  COUNT(DISTINCT p.person_id) AS patient_count
FROM {schema}.person p
LEFT JOIN race_concepts rc ON p.race_concept_id = rc.concept_id
GROUP BY rc.race;
```

**Pattern for any demographic field:**
- Gender: `domain_id = 'Gender'`, join on `p.gender_concept_id`
- Race: `domain_id = 'Race'`, join on `p.race_concept_id`
- Ethnicity: `domain_id = 'Ethnicity'`, join on `p.ethnicity_concept_id`

---

## Category: SINGLE_DRUG

**Query:** "Patients taking drug X"

```sql
WITH drug_source AS (
  SELECT concept_id FROM {schema}.concept
  WHERE vocabulary_id = 'RxNorm' AND concept_code = '{code}' AND invalid_reason IS NULL
),
drug_mapped AS (
  SELECT concept_id_2 AS concept_id
  FROM drug_source ds
  JOIN {schema}.concept_relationship cr ON ds.concept_id = cr.concept_id_1
  WHERE cr.relationship_id = 'Maps to'
),
drug_concepts AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM drug_mapped dm
  JOIN {schema}.concept c ON dm.concept_id = c.concept_id
  JOIN {schema}.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT de.person_id) AS patient_count
FROM {schema}.drug_exposure de
JOIN drug_concepts dc ON de.drug_concept_id = dc.concept_id;
```

---

## Category: SINGLE_CONDITION

**Query:** "Patients with condition X"

```sql
WITH seed AS (
  SELECT c.concept_id AS src_id FROM {schema}.concept c
  WHERE c.vocabulary_id = 'SNOMED' AND c.concept_code = '{code}' AND c.invalid_reason IS NULL
),
std AS (
  SELECT DISTINCT COALESCE(cr.concept_id_2, s.src_id) AS standard_id
  FROM seed s
  LEFT JOIN {schema}.concept_relationship cr ON cr.concept_id_1 = s.src_id
    AND cr.relationship_id = 'Maps to' AND cr.invalid_reason IS NULL
),
desc_cond AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM std sa
  JOIN {schema}.concept_ancestor ca ON ca.ancestor_concept_id = sa.standard_id
  JOIN {schema}.concept c ON c.concept_id = ca.descendant_concept_id
  WHERE c.standard_concept = 'S' AND c.domain_id = 'Condition' AND c.invalid_reason IS NULL
)
SELECT COUNT(DISTINCT co.person_id) AS patient_count
FROM {schema}.condition_occurrence co
JOIN desc_cond dc ON co.condition_concept_id = dc.concept_id;
```

---

## Category: DRUG_IN_YEAR

**Query:** "Patients taking drug X in year YYYY"

**⚠️ Check BOTH start AND end date to capture exposures spanning the year.**

```sql
WITH drug_source AS (...),
drug_mapped AS (...),
drug_concepts AS (...)
SELECT COUNT(DISTINCT de.person_id) AS patient_count
FROM {schema}.drug_exposure de
JOIN drug_concepts dc ON de.drug_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM de.drug_exposure_start_date) <= {year}
  AND EXTRACT(YEAR FROM de.drug_exposure_end_date) >= {year};
```

---

## Category: CONDITION_IN_YEAR

**Query:** "Patients with condition X in year YYYY"

```sql
WITH seed AS (...), std AS (...), desc_cond AS (...)
SELECT COUNT(DISTINCT co.person_id) AS patient_count
FROM {schema}.condition_occurrence co
JOIN desc_cond dc ON co.condition_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM co.condition_start_date) = {year}
  AND co.condition_start_date IS NOT NULL;
```

---

## Category: ENTITY_AT_AGE

**Query:** "Patients with condition X at age Y"

```sql
WITH seed AS (...), std AS (...), desc_cond AS (...)
SELECT COUNT(DISTINCT p.person_id) AS patient_count
FROM {schema}.person p
JOIN {schema}.condition_occurrence co ON co.person_id = p.person_id
JOIN desc_cond dc ON co.condition_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth = {age}::int;
```

---

## Category: DRUG_AND

**Query:** "Patients taking drug A AND drug B" (no temporal)

**⚠️ Use JOIN approach, NOT INTERSECT.**

```sql
WITH drug1_source AS (...), drug1_mapped AS (...), drug1_concepts AS (...),
     drug2_source AS (...), drug2_mapped AS (...), drug2_concepts AS (...)
SELECT COUNT(DISTINCT dr1.person_id) AS patient_count
FROM {schema}.drug_exposure dr1
JOIN drug1_concepts dc1 ON dr1.drug_concept_id = dc1.concept_id
JOIN {schema}.drug_exposure dr2 ON dr1.person_id = dr2.person_id
JOIN drug2_concepts dc2 ON dr2.drug_concept_id = dc2.concept_id;
```

---

## Category: CONDITION_AND

**Query:** "Patients with condition A AND condition B" (no temporal)

**⚠️ Use JOIN with USING, NOT INTERSECT.**

```sql
WITH seed_a AS (...), std_a AS (...), desc_a AS (...),
     seed_b AS (...), std_b AS (...), desc_b AS (...),
persons_a AS (
  SELECT DISTINCT co.person_id
  FROM {schema}.condition_occurrence co
  JOIN desc_a da ON co.condition_concept_id = da.concept_id
),
persons_b AS (
  SELECT DISTINCT co.person_id
  FROM {schema}.condition_occurrence co
  JOIN desc_b db ON co.condition_concept_id = db.concept_id
)
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM persons_a a
JOIN persons_b b USING (person_id);
```

---

## Category: DRUG_OR

**Query:** "Patients taking drug A OR drug B"

```sql
WITH drug1_source AS (...), drug1_mapped AS (...), drug1_concepts AS (...),
     drug2_source AS (...), drug2_mapped AS (...), drug2_concepts AS (...),
combined_drug_concepts AS (
  SELECT concept_id FROM drug1_concepts
  UNION
  SELECT concept_id FROM drug2_concepts
)
SELECT COUNT(DISTINCT de.person_id) AS patient_count
FROM {schema}.drug_exposure de
JOIN combined_drug_concepts cdc ON de.drug_concept_id = cdc.concept_id;
```

---

## Category: CONDITION_OR

**Query:** "Patients with condition A OR condition B"

```sql
WITH seeds AS (
  SELECT 'SNOMED'::text AS vocabulary_id, '{code_a}'::text AS concept_code
  UNION ALL
  SELECT 'SNOMED'::text, '{code_b}'::text
),
seed_concepts AS (
  SELECT c.concept_id AS src_id
  FROM {schema}.concept c
  JOIN seeds s ON s.vocabulary_id = c.vocabulary_id AND s.concept_code = c.concept_code
  WHERE c.invalid_reason IS NULL
),
std AS (
  SELECT DISTINCT COALESCE(cr.concept_id_2, sc.src_id) AS standard_id
  FROM seed_concepts sc
  LEFT JOIN {schema}.concept_relationship cr ON cr.concept_id_1 = sc.src_id
    AND cr.relationship_id = 'Maps to' AND cr.invalid_reason IS NULL
),
descendants AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM std
  JOIN {schema}.concept_ancestor ca ON ca.ancestor_concept_id = std.standard_id
),
valid_cond AS (
  SELECT d.concept_id FROM descendants d
  JOIN {schema}.concept c ON c.concept_id = d.concept_id
  WHERE c.standard_concept = 'S' AND c.domain_id = 'Condition' AND c.invalid_reason IS NULL
)
SELECT COUNT(DISTINCT co.person_id) AS patient_count
FROM {schema}.condition_occurrence co
JOIN valid_cond vc ON co.condition_concept_id = vc.concept_id;
```

---

## Category: DRUG_WITHIN_DAYS

**Query:** "Patients taking drug A and drug B within N days"

**Uses EXTRACT(epoch) with GREATEST/LEAST (symmetric)**

```sql
WITH drug1_source AS (...), drug1_mapped AS (...), drug1_concepts AS (...),
     drug2_source AS (...), drug2_mapped AS (...), drug2_concepts AS (...),
drug1_exposures AS (
  SELECT dr.person_id, dr.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure dr
  JOIN drug1_concepts d1 ON dr.drug_concept_id = d1.concept_id
),
drug2_exposures AS (
  SELECT dr.person_id, dr.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure dr
  JOIN drug2_concepts d2 ON dr.drug_concept_id = d2.concept_id
)
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM drug1_exposures a
JOIN drug2_exposures b ON a.person_id = b.person_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
    CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
  ) / 86400 AS BIGINT
) <= {days};
```

---

## Category: CONDITION_WITHIN_DAYS

**Query:** "Patients with condition A and condition B within N days"

**⚠️ Uses simple ABS date arithmetic, NOT EXTRACT formula.**

```sql
WITH seed_a AS (...), std_a AS (...), desc_a AS (...),
     seed_b AS (...), std_b AS (...), desc_b AS (...),
a AS (
  SELECT co.person_id, co.condition_start_date::date AS start_date
  FROM {schema}.condition_occurrence co
  JOIN desc_a ON co.condition_concept_id = desc_a.concept_id
),
b AS (
  SELECT co.person_id, co.condition_start_date::date AS start_date
  FROM {schema}.condition_occurrence co
  JOIN desc_b ON co.condition_concept_id = desc_b.concept_id
)
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM a
JOIN b ON a.person_id = b.person_id
WHERE ABS(a.start_date - b.start_date) <= {days};
```

---

## Category: DRUG_FOLLOWED_BY

**Query:** "Drug A followed by drug B"

**⚠️ Uses EXTRACT formula with > 0 (directional)**

```sql
WITH drug1_source AS (...), drug1_mapped AS (...), drug1_concepts AS (...),
     drug2_source AS (...), drug2_mapped AS (...), drug2_concepts AS (...)
SELECT COUNT(DISTINCT dr1.person_id) AS patient_count
FROM {schema}.drug_exposure dr1
JOIN drug1_concepts d1 ON dr1.drug_concept_id = d1.concept_id
JOIN {schema}.drug_exposure dr2 ON dr1.person_id = dr2.person_id
JOIN drug2_concepts d2 ON dr2.drug_concept_id = d2.concept_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(dr2.drug_exposure_start_date AS TIMESTAMP) -
    CAST(dr1.drug_exposure_start_date AS TIMESTAMP)
  ) / 86400 AS BIGINT
) > 0;
```

---

## Category: CONDITION_FOLLOWED_BY

**Query:** "Condition A followed by condition B"

**⚠️ Uses simple date comparison, NOT EXTRACT formula.**

```sql
WITH seed_a AS (...), std_a AS (...), desc_a AS (...),
     seed_b AS (...), std_b AS (...), desc_b AS (...),
occ_a AS (
  SELECT co.person_id, co.condition_start_date::date AS start_date
  FROM {schema}.condition_occurrence co
  JOIN desc_a da ON co.condition_concept_id = da.concept_id
),
occ_b AS (
  SELECT co.person_id, co.condition_start_date::date AS start_date
  FROM {schema}.condition_occurrence co
  JOIN desc_b db ON co.condition_concept_id = db.concept_id
)
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM occ_a a
JOIN occ_b b ON b.person_id = a.person_id AND b.start_date > a.start_date;
```

---

## Category: DRUG_DAYS_AFTER

**Query:** "Drug A more than N days after drug B"

**Uses EXTRACT with > N (directional)**

```sql
WITH drug1_source AS (...), drug1_mapped AS (...), drug1_concepts AS (...),
     drug2_source AS (...), drug2_mapped AS (...), drug2_concepts AS (...)
SELECT COUNT(DISTINCT dr1.person_id) AS patient_count
FROM {schema}.drug_exposure dr1
JOIN drug1_concepts d1 ON dr1.drug_concept_id = d1.concept_id
JOIN {schema}.drug_exposure dr2 ON dr1.person_id = dr2.person_id
JOIN drug2_concepts d2 ON dr2.drug_concept_id = d2.concept_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(dr2.drug_exposure_start_date AS TIMESTAMP) -
    CAST(dr1.drug_exposure_start_date AS TIMESTAMP)
  ) / 86400 AS BIGINT
) > {days};
```

---

## Category: CONDITION_DAYS_AFTER

**Query:** "Condition A more than N days after condition B"

**⚠️ Uses EXTRACT with >= N (NOT > N)**

```sql
WITH condition1_source AS (...), condition1_mapped AS (...), condition1_concepts AS (...),
     condition2_source AS (...), condition2_mapped AS (...), condition2_concepts AS (...)
SELECT COUNT(DISTINCT con1.person_id) AS patient_count
FROM {schema}.condition_occurrence con1
JOIN condition1_concepts cc1 ON con1.condition_concept_id = cc1.concept_id
JOIN {schema}.condition_occurrence con2 ON con1.person_id = con2.person_id
JOIN condition2_concepts cc2 ON con2.condition_concept_id = cc2.concept_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(con2.condition_start_date AS TIMESTAMP) -
    CAST(con1.condition_start_date AS TIMESTAMP)
  ) / 86400 AS BIGINT
) >= {days};
```

---

## Category: DRUG_AFTER_CONDITION

**Query:** "Drug X after being diagnosed with condition Y" (no days)

```sql
WITH condition_source AS (...), condition_mapped AS (...), condition_concepts AS (...),
     drug_source AS (...), drug_mapped AS (...),
drug_concepts AS (
  SELECT concept_id FROM drug_mapped
),
cond_occ AS (
  SELECT co.person_id, co.condition_start_date::date AS cond_date
  FROM {schema}.condition_occurrence co
  JOIN condition_concepts cc ON co.condition_concept_id = cc.concept_id
),
drug_exp AS (
  SELECT de.person_id, de.drug_exposure_start_date::date AS drug_date
  FROM {schema}.drug_exposure de
  JOIN drug_concepts dc ON de.drug_concept_id = dc.concept_id
),
pairs AS (
  SELECT DISTINCT co.person_id
  FROM cond_occ co
  JOIN drug_exp de ON de.person_id = co.person_id AND de.drug_date > co.cond_date
)
SELECT COUNT(DISTINCT person_id) AS patient_count FROM pairs;
```

---

## Category: DRUG_DAYS_AFTER_CONDITION

**Query:** "Drug X more than N days after condition Y"

```sql
WITH condition_source AS (...), condition_mapped AS (...), condition_concepts AS (...),
     drug_source AS (...), drug_mapped AS (...), drug_concepts AS (...)
SELECT COUNT(DISTINCT con.person_id) AS patient_count
FROM {schema}.condition_occurrence con
JOIN condition_concepts cc ON con.condition_concept_id = cc.concept_id
JOIN {schema}.drug_exposure dr ON con.person_id = dr.person_id
JOIN drug_concepts dc ON dr.drug_concept_id = dc.concept_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(dr.drug_exposure_start_date AS TIMESTAMP) -
    CAST(con.condition_start_date AS TIMESTAMP)
  ) / 86400 AS BIGINT
) > {days};
```

---

## Category: ENTITY_GROUP_BY_YEAR

**Query:** "Patients with condition X grouped by year"

```sql
WITH seed AS (...), std AS (...), desc_cond AS (...)
SELECT EXTRACT(YEAR FROM co.condition_start_date) AS year,
       COUNT(DISTINCT co.person_id) AS patient_count
FROM {schema}.condition_occurrence co
JOIN desc_cond dc ON co.condition_concept_id = dc.concept_id
GROUP BY EXTRACT(YEAR FROM co.condition_start_date)
ORDER BY year;
```

---

## Quick Reference: Key Differences

| Pattern | Drug | Condition |
|---------|------|-----------|
| **Hierarchy** | 3-step basic | 3-step + domain filter |
| **Within N days** | EXTRACT(epoch)/GREATEST/LEAST | `ABS(date1 - date2)` |
| **Followed by** | `EXTRACT(...) > 0` | `date2 > date1` |
| **N days after** | `EXTRACT(...) > N` | `EXTRACT(...) >= N` |
| **AND logic** | JOIN approach | JOIN with USING |

---

## Common Errors

### ❌ WRONG: birth_datetime
```sql
WHERE EXTRACT(YEAR FROM birth_datetime) = 2078
```
### ✅ CORRECT: year_of_birth
```sql
WHERE year_of_birth = 2078
```

### ❌ WRONG: INTERSECT for AND queries
```sql
SELECT person_id FROM drug_a INTERSECT SELECT person_id FROM drug_b
```
### ✅ CORRECT: JOIN approach
```sql
FROM drug_exposure dr1 JOIN drug_exposure dr2 ON dr1.person_id = dr2.person_id
```

### ❌ WRONG: GREATEST/LEAST for directional queries
```sql
WHERE GREATEST(a.date, b.date) - LEAST(a.date, b.date) > 30
```
### ✅ CORRECT: Direct subtraction
```sql
WHERE EXTRACT(epoch FROM (b.date - a.date)) / 86400 > 30
```

---

## Placeholder Reference

| Placeholder | Source |
|-------------|--------|
| `{schema}` | Get_Information_Schema() |
| `{code}` | entity.concept_code |
| `{code_a}`, `{code_b}` | First/second entity concept_code |
| `{days}` | temporal_constraint.value |
| `{year}` | temporal_constraint.value or additional_filters.year |
| `{age}` | additional_filters.age |
