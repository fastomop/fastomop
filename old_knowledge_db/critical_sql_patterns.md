# Critical SQL Patterns for Common Query Types

This document contains PROVEN SQL patterns for query types that frequently fail. Use these templates exactly as written.

---

## Foundation: Concept Hierarchy Expansion

**CRITICAL:** ALL drug and condition queries MUST use the 3-step hierarchy expansion pattern to find all related concepts.

### Why Hierarchy Expansion is Required

OMOP uses concept hierarchies to organize drugs and conditions:
- A drug ingredient (e.g., "Metformin") has many descendants (different strengths, formulations)
- Using just the ingredient concept_id would miss specific formulations
- Using `concept_ancestor` table expands to ALL related formulations automatically

### Standard 3-Step Pattern

**Use this EXACT pattern for EVERY entity in your query:**

```sql
-- Step 1: Find source concept by vocabulary + code
entity_source AS (
  SELECT concept_id
  FROM {schema}.concept
  WHERE vocabulary_id = '{vocabulary}'  -- 'RxNorm' for drugs, 'SNOMED' for conditions
    AND concept_code = '{code}'         -- From semantic agent
    AND invalid_reason IS NULL
),

-- Step 2: Map to standard concept (handles non-standard codes)
entity_mapped AS (
  SELECT concept_id_2 AS concept_id
  FROM entity_source es
  JOIN {schema}.concept_relationship cr ON es.concept_id = cr.concept_id_1
  WHERE cr.relationship_id = 'Maps to'
),

-- Step 3: Expand to ALL descendants via concept_ancestor
entity_concepts AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM entity_mapped em
  JOIN {schema}.concept c ON em.concept_id = c.concept_id
  JOIN {schema}.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
```

### What This Does

| Step | Input | Output | Purpose |
|------|-------|--------|---------|
| 1 (source) | vocabulary='RxNorm', code='312935' | concept_id matching that code | Find the concept by its external identifier |
| 2 (mapped) | Source concept_id | Standard concept_id via 'Maps to' | Handle non-standard or deprecated codes |
| 3 (concepts) | Standard concept_id | ALL descendant concept_ids | Include all formulations, strengths, brands |

### Example: Metformin Hierarchy

```
Input: vocabulary_id='RxNorm', concept_code='6809'

Step 1 → concept_id = 1503297 (Metformin ingredient)
Step 2 → concept_id = 1503297 (already standard, no mapping needed)
Step 3 → Expands to:
  - 1503297 (Metformin)
  - 1580747 (Metformin 500 MG)
  - 1580411 (Metformin 850 MG)
  - 860975 (Metformin 500 MG Oral Tablet)
  - 860981 (Metformin 850 MG Oral Tablet)
  - ... (100+ descendant formulations)
```

**Without this expansion:** Query would only match the ingredient concept, missing all prescriptions of specific formulations → Wrong patient count.

**With this expansion:** Query matches ALL formulations → Correct patient count.

---

## Foundation: Temporal Constraints

**CRITICAL:** When the semantic agent provides a `temporal_constraint` in the context, you MUST add temporal logic to your SQL query.

### When to Apply Temporal Logic

**Trigger:** Semantic context contains `"temporal_constraint": {"type": "within", "value": N, "unit": "days"}`

**Apply to:** ANY query with temporal constraints, regardless of:
- Number of entities (1, 2, 3, 4+)
- Entity type (drugs, conditions, procedures)
- Query type (single, intersection, union)

### Temporal Constraint Pattern (Universal)

**Core principle:** Calculate the time span between events and check if it's within N days.

**Formula:**
```
Days between events = (Latest event date - Earliest event date) / 86400
Check: Days between events <= N
```

### Pattern 1: Single Entity with Temporal Constraint

**Use case:** "Patients taking Drug A within 30 days of [baseline/diagnosis/etc.]"

**Note:** Single entity temporal queries are rare. Most temporal queries involve multiple entities.

If you encounter this pattern, you likely need additional context (e.g., "within 30 days of diagnosis"). Consult the semantic context for `additional_filters`.

---

### Pattern 2: Two Entities with Temporal Constraint

**Use case:** "Patients taking Drug A and Drug B within 30 days"

**Meaning:** Find patients where Drug A and Drug B were prescribed within 30 days of each other.

**Algorithm:** Start date span (NOT overlap-based for 2 entities)
- Calculate: `GREATEST(start_A, start_B) - LEAST(start_A, start_B)`
- Check: Span <= 30 days

**Template:**

```sql
WITH drug1_source AS (
  SELECT concept_id FROM {schema}.concept
  WHERE vocabulary_id = '{vocab}' AND concept_code = '{code}' AND invalid_reason IS NULL
),
drug1_mapped AS (
  SELECT concept_id_2 AS concept_id
  FROM drug1_source ds
  JOIN {schema}.concept_relationship cr ON ds.concept_id = cr.concept_id_1
  WHERE cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
  SELECT DISTINCT ca.descendant_concept_id AS concept_id
  FROM drug1_mapped dm
  JOIN {schema}.concept c ON dm.concept_id = c.concept_id
  JOIN {schema}.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),

-- Repeat for drug2_source, drug2_mapped, drug2_concepts

-- Create exposure CTEs with START dates only
drug1_exposures AS (
  SELECT de.person_id, de.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
),
drug2_exposures AS (
  SELECT de.person_id, de.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug2_concepts)
)

-- Apply temporal constraint
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM drug1_exposures a
JOIN drug2_exposures b ON a.person_id = b.person_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
    CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
  ) / 86400 AS BIGINT
) <= 30;
```

**Key points:**
- Use `drug_exposure_start_date` only (NO end_date for 2 entities)
- `GREATEST` finds the later start date
- `LEAST` finds the earlier start date
- `EXTRACT(epoch FROM ...)` converts date difference to seconds
- Divide by 86400 to convert seconds to days
- Replace `30` with the actual day value from temporal_constraint

---

### Pattern 3: Three Entities with Temporal Constraint

**Use case:** "Patients taking Drug A, Drug B, and Drug C within 30 days"

**Algorithm:** Same as 2 entities, extended to 3 start dates

**Template:**

```sql
-- [Hierarchy expansion for drug1, drug2, drug3 - same as above]

-- Create exposure CTEs
drug1_exposures AS (
  SELECT de.person_id, de.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
),
drug2_exposures AS (
  SELECT de.person_id, de.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug2_concepts)
),
drug3_exposures AS (
  SELECT de.person_id, de.drug_exposure_start_date AS start_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug3_concepts)
)

-- Apply temporal constraint with 3-way comparison
SELECT COUNT(DISTINCT a.person_id) AS patient_count
FROM drug1_exposures a
JOIN drug2_exposures b ON a.person_id = b.person_id
JOIN drug3_exposures c ON a.person_id = c.person_id
WHERE CAST(
  EXTRACT(epoch FROM
    CAST(GREATEST(a.start_date, b.start_date, c.start_date) AS TIMESTAMP) -
    CAST(LEAST(a.start_date, b.start_date, c.start_date) AS TIMESTAMP)
  ) / 86400 AS BIGINT
) <= 30;
```

**Key points:**
- Extend `GREATEST(...)` and `LEAST(...)` to include all entity start dates
- Pattern scales naturally from 2 to 3 entities
- Same algorithm: start date span, not overlap-based

---

### Pattern 4: Four or More Entities with Temporal Constraint

**Use case:** "Patients taking Drug A, B, C, D within 30 days"

**IMPORTANT:** For 4+ entities, use overlap-based algorithm (different from 2-3 entities)

**Algorithm:** Exposure period overlap (NOT start date span)
- Find periods where ALL drugs are simultaneously active
- Calculate overlap duration
- Check: Overlap duration <= 30 days

**Template:**

```sql
-- [Hierarchy expansion for drug1, drug2, drug3, drug4]

-- Create exposure CTEs with START and END dates
drug1_exposures AS (
  SELECT DISTINCT
    de.person_id,
    de.drug_exposure_start_date::date AS start_date,
    COALESCE(de.drug_exposure_end_date::date, de.drug_exposure_start_date::date) AS end_date
  FROM {schema}.drug_exposure de
  WHERE de.drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
),
-- Repeat for drug2, drug3, drug4

-- Find overlapping periods
overlapping_quads AS (
  SELECT DISTINCT
    a.person_id,
    GREATEST(a.start_date, b.start_date, c.start_date, d.start_date) AS overlap_start,
    LEAST(a.end_date, b.end_date, c.end_date, d.end_date) AS overlap_end
  FROM drug1_exposures a
  JOIN drug2_exposures b ON a.person_id = b.person_id
    AND b.start_date <= a.end_date AND b.end_date >= a.start_date
  JOIN drug3_exposures c ON a.person_id = c.person_id
    AND c.start_date <= a.end_date AND c.end_date >= a.start_date
    AND c.start_date <= b.end_date AND c.end_date >= b.start_date
  JOIN drug4_exposures d ON a.person_id = d.person_id
    AND d.start_date <= a.end_date AND d.end_date >= a.start_date
    AND d.start_date <= b.end_date AND d.end_date >= b.start_date
    AND d.start_date <= c.end_date AND d.end_date >= c.start_date
)

-- Check overlap duration
SELECT COUNT(DISTINCT person_id) AS patient_count
FROM overlapping_quads
WHERE overlap_end >= overlap_start
  AND (overlap_end - overlap_start) <= 30;
```

**Key differences from 2-3 entity pattern:**
- ✅ Use BOTH start_date AND end_date (with COALESCE for NULL end dates)
- ✅ JOIN with overlap conditions: `start <= end AND end >= start`
- ✅ Calculate overlap window: `GREATEST(starts)` to `LEAST(ends)`
- ✅ Check overlap duration instead of start date span

**For 5, 6, or more entities:** Extend the pattern by adding more JOINs with pairwise overlap conditions.

---

### Temporal Pattern Decision Tree

```
IF semantic_context has temporal_constraint:

  entity_count = number of entities in semantic_context

  IF entity_count <= 3:
    Use Pattern 2 or 3: Start date span algorithm
    - Exposure CTEs with start_date only
    - GREATEST/LEAST on start dates
    - EXTRACT(epoch) / 86400 <= N

  ELIF entity_count >= 4:
    Use Pattern 4: Overlap-based algorithm
    - Exposure CTEs with start_date AND end_date
    - JOIN with overlap conditions
    - Calculate overlap window
    - Check overlap duration <= N
```

---

### Why Two Different Algorithms?

**For 2-3 entities (start date span):**
- Simpler and faster
- Good approximation: "prescribed within N days of each other"
- Lower computational complexity
- Matches ground truth for 2-3 entity queries

**For 4+ entities (overlap-based):**
- More accurate: "simultaneously active within N days"
- Prevents false positives from staggered prescriptions
- Required for accurate results with many entities
- Matches ground truth for 4+ entity queries

**Example showing the difference:**

Patient timeline:
```
Drug A: Days 1-10
Drug B: Days 15-25
Drug C: Days 30-40
Drug D: Days 45-55
```

**Start date span (2-3 entity algorithm):**
- Span: Day 45 - Day 1 = 44 days
- Result: ❌ Excluded (> 30 days)

**If we had only 2 drugs (A and B):**
- Span: Day 15 - Day 1 = 14 days
- Result: ✅ Included (< 30 days, even though they don't overlap!)

**Overlap-based (4+ entity algorithm):**
- No period where all 4 drugs overlap
- overlap_end < overlap_start
- Result: ❌ Excluded (correct - no simultaneous use)

---

## Foundation: Demographics Queries

**Use case:** Count or group patients by demographic attributes (gender, ethnicity, race, year_of_birth, location)

**CRITICAL:**
- ALWAYS join to concept table to resolve concept_ids to human-readable names
- Use COALESCE(..., 'Unknown') for NULL concept IDs
- person.year_of_birth is a direct column (NOT birth_datetime)
- Do NOT use EXTRACT(YEAR FROM birth_datetime) - use year_of_birth directly

### Template: Demographics Grouping

```sql
-- Example: Patients grouped by gender and ethnicity
WITH gender_concepts AS (
  SELECT concept_id, concept_name AS gender_name
  FROM {schema}.concept
  WHERE domain_id = 'Gender' AND standard_concept = 'S'
),
ethnicity_concepts AS (
  SELECT concept_id, concept_name AS ethnicity_name
  FROM {schema}.concept
  WHERE domain_id = 'Ethnicity' AND standard_concept = 'S'
)
SELECT
  COALESCE(gc.gender_name, 'Unknown') AS gender,
  COALESCE(ec.ethnicity_name, 'Unknown') AS ethnicity,
  COUNT(DISTINCT p.person_id) AS patient_count
FROM {schema}.person p
LEFT JOIN gender_concepts gc ON p.gender_concept_id = gc.concept_id
LEFT JOIN ethnicity_concepts ec ON p.ethnicity_concept_id = ec.concept_id
GROUP BY gc.gender_name, ec.ethnicity_name;
```

### Template: Year of Birth Grouping

**CRITICAL:** year_of_birth is a direct integer column in person table

```sql
-- Example: Distribution by year of birth
SELECT
  year_of_birth,
  COUNT(DISTINCT person_id) AS patient_count
FROM {schema}.person
GROUP BY year_of_birth
ORDER BY year_of_birth;
```

### Template: Multiple Demographics with Year

```sql
-- Example: Patients grouped by ethnicity and year of birth
WITH ethnicity_concepts AS (
  SELECT concept_id, concept_name AS ethnicity_name
  FROM {schema}.concept
  WHERE domain_id = 'Ethnicity' AND standard_concept = 'S'
)
SELECT
  COALESCE(ec.ethnicity_name, 'Unknown') AS ethnicity,
  p.year_of_birth,
  COUNT(DISTINCT p.person_id) AS patient_count
FROM {schema}.person p
LEFT JOIN ethnicity_concepts ec ON p.ethnicity_concept_id = ec.concept_id
GROUP BY ec.ethnicity_name, p.year_of_birth
ORDER BY ethnicity, year_of_birth;
```

### Key Points

- **year_of_birth:** Direct column (integer), no EXTRACT needed
- **Concept resolution:** Always join to concept table for gender/ethnicity/race
- **COALESCE:** Use 'Unknown' for NULL concept IDs
- **Location:** Join to location table using person.location_id

### Common Demographic Concept Domains

- Gender: `domain_id = 'Gender'`
- Ethnicity: `domain_id = 'Ethnicity'`
- Race: `domain_id = 'Race'`
- Location: Separate location table, join on person.location_id

---

## Pattern: Age-Constrained Queries

**Use case:** Find patients with a condition/procedure/drug at a specific age

**Critical requirement:** Age must be calculated as age AT THE TIME OF THE EVENT, not current age

### Template (Condition at Age)
```sql
WITH condition_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCABULARY]'
      AND concept_code = '[CODE]'
),
condition_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM condition_source cs
    JOIN base.concept_relationship cr ON cs.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
condition_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM condition_mapped cm
    JOIN base.concept c ON cm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.condition_occurrence co ON p.person_id = co.person_id
JOIN condition_concepts cc ON co.condition_concept_id = cc.concept_id
WHERE EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth = [AGE]
LIMIT 1000;
```

### Template (Drug at Age)
```sql
WITH drug_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCABULARY]'
      AND concept_code = '[CODE]'
),
drug_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.drug_exposure de ON p.person_id = de.person_id
JOIN drug_concepts dc ON de.drug_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM de.drug_exposure_start_date) - p.year_of_birth = [AGE]
LIMIT 1000;
```

### Key Points
- Age formula: `EXTRACT(YEAR FROM event_date) - person.year_of_birth`
- Use event date (condition_start_date, drug_exposure_start_date, etc.)
- NOT current date - age must be at time of event
- Works with year_of_birth (no need for birth_datetime)

### Example
```sql
-- Patients with diabetes diagnosed at age 18
WHERE EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth = 18
```

---

## Pattern: OR Queries (UNION)

**Use case:** Find patients with Drug A OR Drug B (union, not intersection)

**Critical requirement:** Use UNION to combine patient sets, count DISTINCT

### Template (Two Drugs - ALWAYS with Hierarchy Expansion)

**ALWAYS use this template for ALL drug UNION queries**, regardless of specificity.
- Use for ingredient-level drugs (e.g., "Hydrochlorothiazide", "Terfenadine")
- Use for formulation-specific drugs (e.g., "hydrochlorothiazide 25 MG Oral Tablet")
- Hierarchy expansion ensures comprehensive patient matching across all descendants

**CRITICAL:** Use this template EXACTLY as written. Do NOT rename CTEs. The _hierarchy CTEs MUST use ca.descendant_concept_id to expand to all formulations.

```sql
WITH drug1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_A]'
      AND concept_code = '[CODE_A]'
),
drug1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug1_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
    -- ⭐ HIERARCHY EXPANSION via concept_ancestor
    -- Note: concept_ancestor includes self-relationships, so no need for UNION
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug1_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_B]'
      AND concept_code = '[CODE_B]'
),
drug2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug2_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug2_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
combined_drug_concepts AS (
    SELECT concept_id FROM drug1_concepts
    UNION
    SELECT concept_id FROM drug2_concepts
)
SELECT COUNT(DISTINCT person_id)
FROM base.drug_exposure
WHERE drug_concept_id IN (SELECT concept_id FROM combined_drug_concepts)
LIMIT 1000;
```

### Template (Two Conditions - ALWAYS with Hierarchy Expansion)
```sql
WITH condition1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_A]'
      AND concept_code = '[CODE_A]'
),
condition1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM condition1_source cs
    JOIN base.concept_relationship cr ON cs.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
condition1_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM condition1_mapped cm
    JOIN base.concept c ON cm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
condition2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_B]'
      AND concept_code = '[CODE_B]'
),
condition2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM condition2_source cs
    JOIN base.concept_relationship cr ON cs.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
condition2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM condition2_mapped cm
    JOIN base.concept c ON cm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
combined_condition_concepts AS (
    SELECT concept_id FROM condition1_concepts
    UNION
    SELECT concept_id FROM condition2_concepts
)
SELECT COUNT(DISTINCT person_id)
FROM base.condition_occurrence
WHERE condition_concept_id IN (SELECT concept_id FROM combined_condition_concepts)
LIMIT 1000;
```

### Key Points
- UNION combines patient sets (not INTERSECT)
- COUNT(DISTINCT person_id) ensures no duplicates
- Each entity gets its own CTE for concept expansion
- Final query wraps UNIONed results

---

## Pattern: AND Queries (Intersection - 2 Entities)

**Use case:** Find patients with Drug A AND Drug B (both required)

**Critical requirement:** Use EXISTS clauses to find patients having BOTH

**IMPORTANT:** ALWAYS use hierarchy expansion for all drug queries (matches ground truth patterns)

### Template (Two Drugs - ALWAYS with Hierarchy Expansion)

```sql
WITH drug1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_A]'
      AND concept_code = '[CODE_A]'
),
drug1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug1_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug1_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_B]'
      AND concept_code = '[CODE_B]'
),
drug2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug2_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug2_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
WHERE EXISTS (
    SELECT 1 FROM base.drug_exposure de1
    WHERE de1.person_id = p.person_id
      AND de1.drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure de2
    WHERE de2.person_id = p.person_id
      AND de2.drug_concept_id IN (SELECT concept_id FROM drug2_concepts)
)
LIMIT 1000;
```

### Key Points
- EXISTS clauses check for presence of each drug
- Anchor on person table
- Each EXISTS is independent (different table aliases)
- Returns count of patients having BOTH

---

## Pattern: Multi-Entity Intersection (3+ Entities)

**Use case:** Find patients with Drug A AND Drug B AND Drug C AND Drug D (all required)

**Critical requirement:** One EXISTS clause per entity

### Template (4 Drugs)
```sql
WITH drug1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_1]'
      AND concept_code = '[CODE_1]'
),
drug1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug1_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug1_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_2]'
      AND concept_code = '[CODE_2]'
),
drug2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug2_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug2_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug3_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_3]'
      AND concept_code = '[CODE_3]'
),
drug3_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug3_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug3_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug3_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug4_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_4]'
      AND concept_code = '[CODE_4]'
),
drug4_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug4_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug4_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug4_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
WHERE EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug2_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug3_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug4_concepts)
)
LIMIT 1000;
```

### Key Points
- One CTE per drug for concept expansion
- One EXISTS clause per drug in final query
- Anchor on person table
- Add as many EXISTS as needed (no limit)
- Each EXISTS uses same table but different CTE

### Scaling
For N drugs, create N CTEs and N EXISTS clauses. Pattern is fully extensible.

---

## Pattern: Demographics Only (No Medical Concepts)

**Use case:** Count patients by gender, race, age range

### Template (Gender)
```sql
SELECT COUNT(DISTINCT person_id)
FROM base.person
WHERE gender_concept_id = [CONCEPT_ID]
LIMIT 1000;
```

**Gender concept IDs:**
- Female: 8532
- Male: 8507

### Template (Race)
```sql
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.concept c
  ON p.race_concept_id = c.concept_id
WHERE c.concept_name = '[RACE_NAME]'
  AND c.domain_id = 'Race'
LIMIT 1000;
```

### Template (Age Range by Birth Year)
```sql
SELECT COUNT(DISTINCT person_id)
FROM base.person
WHERE year_of_birth BETWEEN [START_YEAR] AND [END_YEAR]
LIMIT 1000;
```

---

## Pattern: Temporal Constraints (Drug AND Drug within N days)

**Use case:** Find patients with TWO drug exposures within a specified time window

**CRITICAL REQUIREMENT:** Use the EXACT date arithmetic formula below. DO NOT use DATEDIFF, DATE_DIFF, julianday, or simple subtraction.

**Why this formula:** Battle-tested on 680+ queries, works across SQL engines (DuckDB, PostgreSQL), handles edge cases correctly.

### ⚠️ DATE ARITHMETIC - CRITICAL FORMULA

**NEVER use these (they will fail):**
- ❌ `DATEDIFF(date1, date2)`
- ❌ `DATE_DIFF('day', date1, date2)`
- ❌ `julianday(date1) - julianday(date2)`
- ❌ `ABS(date1 - date2)`

**ALWAYS use this formula:**
```sql
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(date1, date2) AS TIMESTAMP) -
        CAST(LEAST(date1, date2) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
```

**What this does:**
- `GREATEST/LEAST`: Ensures later_date - earlier_date (always positive)
- `EXTRACT(epoch FROM ...)`: Converts to seconds since epoch
- `/ 86400`: Converts seconds to days (86400 seconds/day)
- `CAST(... AS BIGINT)`: Integer days for comparison
- Works in DuckDB, PostgreSQL, and most SQL engines

---

### Template (Drug AND Drug Temporal - ALWAYS with Hierarchy)

**ALWAYS use this template for ALL drug temporal queries**, regardless of specificity.
- Use for ingredient-level drugs (e.g., "metformin", "lisinopril")
- Use for formulation-specific drugs (e.g., "metformin 500 MG Oral Tablet")
- Query: "Drug A and Drug B within N days"

**Critical:** Uses concept_ancestor to expand to all formulations (matches ground truth)

```sql
WITH drug1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_A]'
      AND concept_code = '[CODE_A]'
),
drug1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug1_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug1_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug1_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug1_concepts d1 ON de.drug_concept_id = d1.concept_id
),
drug2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_B]'
      AND concept_code = '[CODE_B]'
),
drug2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM drug2_source ds
    JOIN base.concept_relationship cr ON ds.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
drug2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug2_mapped dm
    JOIN base.concept c ON dm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug2_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug2_concepts d2 ON de.drug_concept_id = d2.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM drug1_exposures a
JOIN drug2_exposures b ON a.person_id = b.person_id
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
        CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
LIMIT 1000;
```

**Placeholders:**
- `[VOCAB_A]` = First drug vocabulary (usually 'RxNorm')
- `[CODE_A]` = First drug concept_code
- `[VOCAB_B]` = Second drug vocabulary
- `[CODE_B]` = Second drug concept_code
- `[N_DAYS]` = Number of days (e.g., 30, 60, 90)

---

### Template (Condition AND Condition Temporal - ALWAYS with Hierarchy)

**Use case:** Find patients with two conditions diagnosed within N days

**Example:** "Patients with diabetes and hypertension within 90 days"

```sql
WITH condition1_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_A]'
      AND concept_code = '[CODE_A]'
),
condition1_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM condition1_source cs
    JOIN base.concept_relationship cr ON cs.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
condition1_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM condition1_mapped cm
    JOIN base.concept c ON cm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
condition1_occurrences AS (
    SELECT co.person_id,
           co.condition_start_date AS start_date
    FROM base.condition_occurrence co
    JOIN condition1_concepts c1 ON co.condition_concept_id = c1.concept_id
),
condition2_source AS (
    SELECT concept_id
    FROM base.concept
    WHERE vocabulary_id = '[VOCAB_B]'
      AND concept_code = '[CODE_B]'
),
condition2_mapped AS (
    SELECT concept_id_2 AS concept_id
    FROM condition2_source cs
    JOIN base.concept_relationship cr ON cs.concept_id = cr.concept_id_1
    WHERE cr.relationship_id = 'Maps to'
),
condition2_concepts AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM condition2_mapped cm
    JOIN base.concept c ON cm.concept_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
condition2_occurrences AS (
    SELECT co.person_id,
           co.condition_start_date AS start_date
    FROM base.condition_occurrence co
    JOIN condition2_concepts c2 ON co.condition_concept_id = c2.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM condition1_occurrences a
JOIN condition2_occurrences b ON a.person_id = b.person_id
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
        CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
LIMIT 1000;
```

---

### Key Points for Temporal Constraints

1. **Date Formula is NON-NEGOTIABLE**: Use the exact EXTRACT(epoch) formula
2. **Hierarchy Expansion**: ALWAYS use for all drug and condition queries (matches ground truth)
3. **Table Aliases**: `a` for first entity, `b` for second entity
4. **CTEs**: Separate CTEs for seed → standard → hierarchy → exposures/occurrences
5. **GREATEST/LEAST**: Handles any date order (earlier or later doesn't matter)

---

### Search Keywords for KB Retrieval

**Database agent should search for:**
- "Drug AND temporal hierarchy" → Use drug temporal template (always with hierarchy)
- "Condition AND temporal hierarchy" → Use condition temporal template
- "within N days date arithmetic" → Get the correct EXTRACT formula
- "Drug UNION hierarchy" → Use drug UNION template (always with hierarchy)
- "AND queries hierarchy" → Use drug AND template (always with hierarchy)

---

## Quick Reference: Query Type → Pattern

| User Query | Query Type | Pattern to Use |
|------------|------------|----------------|
| "Drug A or Drug B" | union | OR Queries (UNION) |
| "Drug A and Drug B" | intersection | AND Queries (Intersection) |
| "Drug A, Drug B, Drug C, Drug D" | multi_intersection | Multi-Entity Intersection |
| "Condition X at age Y" | age_constrained | Age-Constrained Queries (Condition) |
| "Drug X at age Y" | age_constrained | Age-Constrained Queries (Drug) |
| "How many patients are female?" | demographics | Demographics Only (Gender) |

---

## Common Mistakes to Avoid

### ❌ WRONG: Date arithmetic with DATEDIFF (WILL FAIL)
```sql
-- These functions DO NOT EXIST in this database:
WHERE DATEDIFF(date1, date2) <= 30  -- FAILS
WHERE DATE_DIFF('day', date1, date2) <= 30  -- FAILS
WHERE julianday(date1) - julianday(date2) <= 30  -- FAILS
WHERE ABS(date1 - date2) <= 30  -- UNRELIABLE
```

### ✓ CORRECT: Use EXTRACT(epoch) formula
```sql
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(date1, date2) AS TIMESTAMP) -
        CAST(LEAST(date1, date2) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= 30
```

### ❌ WRONG: Age = current age
```sql
WHERE (EXTRACT(YEAR FROM CURRENT_DATE) - year_of_birth) = 18
```

### ✓ CORRECT: Age at event
```sql
WHERE (EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth) = 18
```

### ❌ WRONG: OR query using INTERSECT
```sql
SELECT person_id FROM drug_a
INTERSECT
SELECT person_id FROM drug_b
```

### ✓ CORRECT: OR query using UNION
```sql
SELECT person_id FROM drug_a
UNION
SELECT person_id FROM drug_b
```

### ❌ WRONG: Multi-entity with JOINs
```sql
FROM drug_exposure de1
JOIN drug_exposure de2 ON de1.person_id = de2.person_id
JOIN drug_exposure de3 ON de1.person_id = de3.person_id
```

### ✓ CORRECT: Multi-entity with EXISTS
```sql
WHERE EXISTS (drug1)
  AND EXISTS (drug2)
  AND EXISTS (drug3)
```

---

## Summary

Use these patterns EXACTLY as written. They are battle-tested and correct:

1. **Age constraints**: `EXTRACT(YEAR FROM event_date) - year_of_birth`
2. **OR queries**: UNION with COUNT(DISTINCT person_id), ALWAYS use hierarchy expansion
3. **AND queries**: Multiple EXISTS clauses, ALWAYS use hierarchy expansion
4. **Multi-entity**: One EXISTS per entity, ALWAYS use hierarchy expansion
5. **Temporal queries**: Use EXTRACT(epoch) formula, ALWAYS use hierarchy expansion
6. **Demographics**: Direct person table query (no hierarchy needed)
7. **Hierarchy expansion**: ALWAYS use concept_ancestor for all drug/condition queries, regardless of specificity

Do NOT deviate from these patterns unless you have a specific reason documented in code.
