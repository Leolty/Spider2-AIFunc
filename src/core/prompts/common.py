"""
Common prompt components that can be reused across different tasks.
"""

# ============================================================================
# Reusable Components
# ============================================================================

DETERMINISM_REQUIREMENTS = """<determinism_requirements>
The SQL query and instruction you generate will serve as the "Ground Truth" or Benchmark for evaluating other AI models. To be a valid benchmark, your output must satisfy TWO dimensions of determinism:

**Dimension 1: Execution Determinism**
The same SQL query must produce identical results every time it is executed. This means all AI function parameters (categories, thresholds, limits, reference texts, aggregation instructions) must be explicitly and completely defined in the SQL itself.

**Dimension 2: Specification Determinism**
The instruction must uniquely specify the SQL implementation. Given your instruction, any qualified engineer should be able to write exactly one SQL query, not multiple possible variations. This means the instruction must contain all implementation-critical details: the exact input format templates, complete parameter values, precise thresholds, and verbatim text strings that will appear in the AI function calls.

Both dimensions are equally critical. A benchmark fails if either:
- The SQL produces different results on re-execution (Dimension 1 violation), OR
- The instruction could reasonably map to multiple different SQL implementations (Dimension 2 violation)

**Model Stability Guarantee:** All AI functions use temperature=0, meaning identical inputs always produce identical outputs. Your responsibility is to ensure parameter stability in both the SQL (Dimension 1) and the instruction (Dimension 2).

---

The following sections detail the determinism requirements for each AI function. For each function, we explain both what the SQL must contain (Execution Determinism) and what the instruction must contain (Specification Determinism). The examples are intentionally simplified to illustrate core principles; real-world queries will be more complex, but the same requirements apply.

---

**AI_SIMILARITY (Semantic Ranking & Filtering)**

AI_SIMILARITY calculates a floating-point score representing semantic closeness between two texts. Because it returns a continuous score, you must define clear boundaries to create a stable, bounded result set.

*Execution Determinism (SQL Requirements):*

The SQL must bound the result set using one of two strategies:
1. Ranking Strategy: If sorting by similarity, append a specific LIMIT clause (e.g., LIMIT 10, LIMIT 50).
2. Filtering Strategy: If filtering by similarity, use a concrete numeric threshold (e.g., > 0.5, >= 0.65).

Without one of these bounds, the result set size is undefined and may vary. The reference text in the SQL must be uniquely determined, either a fixed string literal specified in the instruction, or a value from a specific table location (e.g., "the description of product with id=1"). Do not invent or expand the reference text beyond what the instruction specifies.

*Specification Determinism (Instruction Requirements):*

The instruction must contain:
- The reference text, specified in one of two ways:
  - As a quoted string literal (e.g., "most similar to 'battery drains quickly'"), OR
  - As a reference to a specific table value (e.g., "most similar to the description of the product with id=1")
- The bounding strategy: either the exact limit (e.g., "top 10") or the exact threshold (e.g., "similarity score greater than 0.5")

If the instruction says "find reviews similar to battery issues" without quotes or a specific table reference, an engineer might invent variations like 'battery issues; battery problems; power drain'. The instruction must clearly specify the exact source of the reference text.

*Example - Indeterminate Approach:*

    Instruction: "Find reviews similar to battery issues."
    SQL: SELECT * FROM reviews ORDER BY AI_SIMILARITY(text, 'battery issues; battery problems; power drain');
    
    Problems:
    - Execution: No LIMIT or threshold, so result set size is unbounded
    - Specification: "battery issues" has no quotes, so the engineer invented an expanded reference text

*Example - Deterministic Approach:*

    Instruction: "Find the top 10 reviews most similar to 'battery drains quickly'."
    SQL: SELECT * FROM reviews ORDER BY AI_SIMILARITY(text, 'battery drains quickly') DESC LIMIT 10;
    
    Why it works:
    - Execution: LIMIT 10 bounds the result set
    - Specification: The quoted reference text 'battery drains quickly' and "top 10" are both explicit in the instruction

*Output Column Warning:*

Do NOT include raw AI_SIMILARITY scores as output columns in your final SELECT. High-precision floating-point values (e.g., 0.3014192283153534) are difficult to validate for determinism. Instead:
- Use AI_SIMILARITY only in ORDER BY (e.g., "find the most relevant...") or WHERE clauses (e.g., "similarity > 0.5")
- If you want to show relevance in the output, modify the analytical question to use ranking ("top N most similar") rather than displaying scores
- Alternatively, convert scores to discrete categories using CASE WHEN (e.g., CASE WHEN score > 0.7 THEN 'High' WHEN score > 0.4 THEN 'Medium' ELSE 'Low' END)

---

**AI_CLASSIFY (Categorization)**

AI_CLASSIFY assigns text to one or more categories from a list you provide. The function restricts its output to exactly the options in your list, making the category list the critical determinism parameter.

*Execution Determinism (SQL Requirements):*

The SQL must contain:
- A complete, closed list of category strings (e.g., ['High', 'Medium', 'Low'])
- If using label descriptions (to clarify what each category means), the complete description string for each label
- If using task_description in the config object (to explain the overall classification task), the exact task description text

"Other" is valid only if explicitly included as a string literal. Do not use open-ended phrases that invite dynamic category invention.

*Specification Determinism (Instruction Requirements):*

The instruction must contain:
- The complete category list, verbatim (e.g., "classify into exactly one of ['University', 'Corporation', 'Government', 'Other']")
- What is being classified, explicitly name the field or content being used as input:
  - For single column: state the field name and whether it's used as-is or with preprocessing (e.g., "classified into [...] based on organization name" or "classified into [...] based on product description after replacing [xxx] with [yyy]")
  - For multiple columns via CONCAT/PROMPT: the exact template format (e.g., "based on a description formatted as 'Lighting: {lighting}, Weather: {weather}'")
- If you use label descriptions, the exact description string for each label must appear in the instruction (e.g., "where 'urgent' means 'needs immediate attention within 24 hours', 'normal' means 'standard priority request'...")
- If you use task_description, the exact task description string must appear in the instruction (e.g., "with task guidance: 'Classify customer complaints by root cause department'")

Different engineers might format or preprocess the input differently, leading to different classification results. Always be explicit about what text goes into the classifier.

*Example - Indeterminate Approach (Category List):*

    Instruction: "Classify into Support, Billing, and anything else relevant."
    SQL: AI_CLASSIFY(text, ['Support', 'Billing', 'Technical', 'Sales'])
    
    Problems:
    - Specification: "anything else relevant" is vague; engineer invented 'Technical' and 'Sales'
    - Different engineers would produce different category lists

*Example - Deterministic Approach (Category List):*

    Instruction: "Classify each ticket into exactly one of ['Support', 'Billing', 'Other']."
    SQL: AI_CLASSIFY(text, ['Support', 'Billing', 'Other'])
    
    Why it works: The complete category list is explicit in both instruction and SQL.

*Example - Indeterminate Approach (Input Formatting):*

    Instruction: "Classify accident risk level based on the combined assessment of lighting conditions, weather conditions, and road surface conditions into one of ['High Risk', 'Moderate Risk', 'Low Risk']."
    
    Problems:
    - Specification: "combined assessment" doesn't specify HOW to combine the columns
    - Engineer A might write: CONCAT('Lighting: ', lighting, ', Weather: ', weather, ', Road: ', surface)
    - Engineer B might write: CONCAT(lighting, ' | ', weather, ' | ', surface)
    - Engineer C might write: CONCAT('Conditions - ', lighting, '/', weather, '/', surface)
    - Each produces different AI_CLASSIFY inputs, potentially yielding different classifications

*Example - Deterministic Approach (Input Formatting):*

    Instruction: "Classify each accident into exactly one of ['High Risk', 'Moderate Risk', 'Low Risk'] based on a combined description formatted as 'Lighting: {lighting}, Weather: {weather}, Road surface: {surface}, Road condition: {road_condition}'."
    SQL: AI_CLASSIFY(CONCAT('Lighting: ', lighting, ', Weather: ', weather, ', Road surface: ', surface, ', Road condition: ', road_condition), ['High Risk', 'Moderate Risk', 'Low Risk'])
    
    Why it works: The exact CONCAT template is embedded in the instruction. Any engineer would produce the same input string.

*Example - Indeterminate Approach (Label Descriptions):*

    Instruction: "Filter to slides classified as 'Excellent' or 'Good' quality from ['Excellent', 'Good', 'Acceptable', 'Poor'] based on metadata completeness and technical specifications."
    
    Problems:
    - Specification: What criteria define "Excellent" vs "Good"? The instruction doesn't say.
    - Engineer A might use label description: 'high resolution with complete metadata'
    - Engineer B might use label description: 'pixel spacing under 0.5mm and lossless compression'
    - Different label descriptions yield different classifications

*Example - Deterministic Approach (Label Descriptions):*

    Instruction: "Filter to slides classified as 'Excellent' or 'Good' from the categories ['Excellent', 'Good', 'Acceptable', 'Poor'], where 'Excellent' means 'precise pixel spacing under 0.5mm, resolution above 1000x1000, lossless compression', 'Good' means 'adequate specifications with minor limitations', 'Acceptable' means 'usable but suboptimal', and 'Poor' means 'significant technical deficiencies'."
    SQL: AI_CLASSIFY(
        description, 
        [
            {'label': 'Excellent', 'description': 'precise pixel spacing under 0.5mm, resolution above 1000x1000, lossless compression'},
            {'label': 'Good', 'description': 'adequate specifications with minor limitations'},
            {'label': 'Acceptable', 'description': 'usable but suboptimal'},
            {'label': 'Poor', 'description': 'significant technical deficiencies'}
        ]
    )
    
    Why it works: The exact label description strings are embedded in the instruction. Any engineer would use the same descriptions.

*Return Value Extraction:*

AI_CLASSIFY returns a JSON object, not a plain string. For example, `AI_CLASSIFY(text, ['A', 'B', 'C']) AS category` outputs JSON like `{"labels": ["A"]}`. If you want a clean string value in your output column, you need to extract the label from this JSON structure, for example, by accessing the first element of the `labels` array and casting it to a string.

When validating results, if you see JSON structures like `{"labels": [...]}` in your output columns, it means the label was not properly extracted. Your final output should not contain raw JSON objects, fix the extraction before concluding.

---

**AI_EXTRACT (Structured Extraction)**

AI_EXTRACT pulls structured data from unstructured text using a responseFormat schema. Each field in the schema is defined by an extraction question or description.

*Execution Determinism (SQL Requirements):*

The SQL must contain:
- The complete responseFormat schema with all field names
- The exact extraction question or description for each field

*Specification Determinism (Instruction Requirements):*

The instruction must contain:
- Each field name that will appear in the responseFormat
- The exact extraction question or description for each field (e.g., "using the extraction question: 'What is the effective date? Format: YYYY-MM-DD'")

If the instruction just says "extract the effective date," an engineer might write the extraction question as 'Extract date', 'What is the effective date?', 'Effective date?', or 'What is the effective date? Format: YYYY-MM-DD'. Each variation is a different parameter that could yield different extraction results.

*Example - Indeterminate Approach:*

    Instruction: "Get the effective date from the contract."
    SQL: AI_EXTRACT(text, responseFormat => {'effective_date': 'Extract date'})
    
    Problems:
    - Specification: "Get the effective date" doesn't specify the exact extraction question
    - Another engineer might use 'What is the effective date?' or 'Effective date in YYYY-MM-DD format'

*Example - Deterministic Approach:*

    Instruction: "Extract the effective date into a field named 'effective_date', using the extraction question: 'What is the effective date? Format: YYYY-MM-DD'"
    SQL: AI_EXTRACT(text, responseFormat => {'effective_date': 'What is the effective date? Format: YYYY-MM-DD'})
    
    Why it works: The field name and exact extraction question are both specified in the instruction.

*Return Value Extraction:*

AI_EXTRACT returns a JSON object with your specified field names. For example, `AI_EXTRACT(text, responseFormat => {'effective_date': '...'}) AS extracted` outputs JSON like `{"effective_date": "2024-01-01"}`. If you want clean values in your output columns, you need to extract specific fields from this JSON structure and cast them to the appropriate types.

When validating results, if you see JSON structures like `{"effective_date": "..."}` in your output columns, it means the fields were not properly extracted. Your final output should not contain raw JSON objects, fix the extraction before concluding.

---

**AI_SENTIMENT (Tone Analysis)**

AI_SENTIMENT returns a fixed set of sentiment values: 'positive', 'negative', 'neutral', 'mixed', 'unknown'. It can analyze overall sentiment or sentiment for specific aspects.

*Execution Determinism (SQL Requirements):*

The SQL must:
- Only filter or operate on the exact enum values ('positive', 'negative', 'neutral', 'mixed', 'unknown')
- If analyzing specific aspects, provide the exact category list (e.g., ['Food', 'Service'])
- Use correct Snowflake JSON path syntax to access the results

Do not use subjective human concepts like "angry," "happy," or "good" as filter values, these are not valid return values from the function.

*Specification Determinism (Instruction Requirements):*

The instruction must:
- Use the exact sentiment enum values when describing filters (e.g., "where sentiment is 'negative'" not "where customer is unhappy")
- If analyzing specific aspects, list each aspect with quotes to avoid ambiguity (e.g., "analyze sentiment for the 'Food' and 'Service' aspects" makes it clear there are two separate aspects, not one combined aspect)

*Example - Indeterminate Approach (Invalid Enum):*

    Instruction: "Show me reviews where the customer is unhappy."
    SQL: WHERE AI_SENTIMENT(text):categories[0].sentiment = 'unhappy'
    
    Problems:
    - Execution: 'unhappy' is not a valid enum value; query will fail or return no results
    - Specification: "unhappy" maps ambiguously to the function's capabilities

*Example - Deterministic Approach (Overall Sentiment):*

    Instruction: "Show me reviews where the overall sentiment is 'negative'."
    SQL: WHERE AI_SENTIMENT(text):categories[0].sentiment = 'negative'
    
    Why it works: Uses the exact enum value 'negative' in both instruction and SQL.

*Example - Indeterminate Approach (Aspects):*

    Instruction: "Analyze sentiment for Food and Service aspects."
    
    Problems:
    - Specification: Is this one aspect 'Food and Service' or two aspects 'Food' and 'Service'?
    - Engineer A might use: ['Food and Service']
    - Engineer B might use: ['Food', 'Service']

*Example - Deterministic Approach (Aspects):*

    Instruction: "Analyze sentiment for the 'Food' and 'Service' aspects separately, filtering to reviews where 'Food' sentiment is 'positive'."
    SQL: WHERE AI_SENTIMENT(text, ['Food', 'Service']):categories[1].sentiment = 'positive'
    
    Why it works: Each aspect is quoted separately, making it unambiguous that there are two distinct aspects.

*Return Value Extraction:*

AI_SENTIMENT returns a JSON object with a `categories` array. For example, `AI_SENTIMENT(text) AS sentiment` outputs JSON like `{"categories": [{"category": "overall", "sentiment": "positive"}]}`. If you want a clean sentiment string in your output column, you need to extract the sentiment value from the appropriate category in this JSON structure.

When validating results, if you see JSON structures like `{"categories": [...]}` in your output columns, it means the sentiment value was not properly extracted. Your final output should not contain raw JSON objects, fix the extraction before concluding.

---

**AI_FILTER (Boolean Semantic Filtering)**

AI_FILTER evaluates whether input meets a natural language condition and returns TRUE or FALSE. The condition phrase is the critical parameter.

*Execution Determinism (SQL Requirements):*

The SQL must contain:
- The exact condition phrase as a string literal
- If combining with column data, the explicit format (using CONCAT or PROMPT)

*Specification Determinism (Instruction Requirements):*

The instruction must contain:
- The exact condition phrase that will be evaluated (e.g., "where the condition 'Python is the primary development language in this repository' evaluates to true")
- If combining with column data, the exact template format (e.g., "concatenating '{condition phrase}: ' with each review")

This is critical because AI_FILTER's behavior depends entirely on the wording of the condition. Slight variations in phrasing can yield different TRUE/FALSE results.

*Example - Indeterminate Approach:*

    Instruction: "Find reviews from satisfied customers."
    SQL: WHERE AI_FILTER(CONCAT('satisfied customer: ', review_text))
    
    Problems:
    - Specification: "satisfied customers" doesn't specify the exact condition phrase
    - Engineer A: 'satisfied customer: '
    - Engineer B: 'customer is satisfied: '
    - Engineer C: 'positive customer feedback - '
    - Each yields different filtering results

*Example - Deterministic Approach:*

    Instruction: "Find reviews where the condition 'The customer is satisfied with both product quality and delivery: ' concatenated with the review text evaluates to true."
    SQL: WHERE AI_FILTER(CONCAT('The customer is satisfied with both product quality and delivery: ', review_text))
    
    Why it works: The exact condition phrase and concatenation format are explicit in the instruction.

*Alternative Natural Phrasing:*

    Instruction: "Find reviews indicating satisfaction, filtered using the phrase 'The customer is satisfied with both product quality and delivery' applied to each review."
    
    This is also acceptable, it specifies the exact phrase while reading more naturally.

---

**AI_AGG (Text Aggregation)**

AI_AGG aggregates multiple text rows into a single summary or analysis based on an instruction you provide. The aggregation instruction is the critical parameter.

*Execution Determinism (SQL Requirements):*

The SQL must contain:
- The exact aggregation instruction as a string literal
- Prefer specific, factual tasks (e.g., "Identify the top 3 complaints") that produce concise outputs, rather than open-ended summaries (e.g., "Summarize everything") that produce lengthy text
- Specify an explicit output format to constrain length. Instead of vague hints like "in one concise sentence", use structured formats like "formatted as: item1; item2; item3" or "Return as: 'Positive: [text]; Negative: [text]'". This produces outputs like "battery life; camera quality; design" rather than "The most commonly praised aspects include the excellent battery life, impressive camera quality, and sleek design."

Note on AI_AGG output stability: The underlying model uses temperature=0, which theoretically guarantees that identical inputs produce identical outputs. However, for open-ended instructions that generate lengthy responses, there may be subtle implementation-level variations. To maximize determinism: (1) use specific instructions that produce shorter, more focused outputs, and (2) most importantly, ensure the input to AI_AGG is itself deterministic, if the input rows or aggregation instruction vary, the output will vary.

*Specification Determinism (Instruction Requirements):*

The instruction must contain:
- The exact aggregation instruction text that will be passed to AI_AGG (e.g., "aggregate using the instruction: 'Identify the top 3 most mentioned positive aspects and the top 3 most mentioned complaints'")

*Example - Indeterminate Approach:*

    Instruction: "Summarize customer feedback for each product."
    SQL: AI_AGG(review_text, 'Summarize the reviews')
    
    Problems:
    - Specification: "Summarize customer feedback" doesn't specify the exact aggregation instruction
    - Engineer A: 'Summarize the reviews'
    - Engineer B: 'Provide a summary of customer feedback'
    - Engineer C: 'What are the key themes in these reviews?'
    - Each is a different parameter

*Example - Deterministic Approach:*

    Instruction: "For each product, aggregate reviews using the instruction: 'List the top 3 positives and top 3 complaints, formatted as: Positives: [item1; item2; item3] | Complaints: [item1; item2; item3]'"
    SQL: AI_AGG(review_text, 'List the top 3 positives and top 3 complaints, formatted as: Positives: [item1; item2; item3] | Complaints: [item1; item2; item3]')
    
    Why it works: The exact aggregation instruction is quoted, and the output format is explicitly specified for brevity and consistency.

---

**Summary: Writing Instructions That Satisfy Specification Determinism**

When writing instructions, always ask yourself: "If another engineer reads only this instruction, could they write the AI function call with different parameters than mine?" If the answer is yes, add more detail.

The goal is to include all specification details while maintaining readable, natural language. Avoid robotic SQL-like syntax, but DO include the substantive content:

    Too Vague (fails Specification Determinism):
    "Classify accidents based on conditions into risk levels."

    Too Robotic (also bad - mentions function name):
    "Execute AI_CLASSIFY with input CONCAT('Lighting: ', col1, ', Weather: ', col2) and labels ['High', 'Medium', 'Low']."

    Natural and Sufficient (preferred):
    "Classify each accident into one of ['High', 'Medium', 'Low'] based on a combined description 'Lighting: {lighting}, Weather: {weather}', where 'High' means 'dangerous conditions requiring immediate caution', 'Medium' means 'moderate caution needed', and 'Low' means 'safe conditions'."

The third example is natural AND sufficient for reproducing the exact AI function parameters. Note: label descriptions (the "where 'X' means '...'" part) are optional, if the category names are self-explanatory (e.g., ['University', 'Corporation', 'Government']), you don't need to add descriptions. The key is that whatever parameters you DO use in your SQL must be specified in the instruction.
</determinism_requirements>"""


AI_FUNCTIONS_REFERENCE = """<ai_functions_reference>
**IMPORTANT**: You MUST use the exact function signatures and syntax shown below. These are the current, supported AI SQL functions. Do NOT use deprecated Snowflake Cortex syntax (like SNOWFLAKE.CORTEX.* prefix) or any other variations.

This reference provides detailed information about key Snowflake Cortex AI functions.

Note: The examples below demonstrate function syntax and basic usage. They are NOT examples of well-designed AI SQL benchmark integrations, see <integration_examples> for guidance on benchmark-quality query design.

---

### AI_CLASSIFY

**Syntax**
`AI_CLASSIFY(<input>, <labels> [, <config_object>])`

**Description**
Categorizes text or images into a specific set of labels you provide. This function is essential for structuring messy data, such as tagging support tickets, organizing feedback, or categorizing product descriptions.

**Parameters**
- `input`: The text string or image file to classify.
- `labels`: An array of category strings OR objects with optional descriptions:
  - Simple: `['sports', 'finance', 'technology']`
  - With descriptions: `[{'label': 'urgent', 'description': 'requires immediate response'}, {'label': 'normal'}]`
  - Descriptions can improve accuracy for ambiguous categories (max 25 words each)
- `config_object` (Optional): A JSON object to define specific behavior:
  - `output_mode`: Set to `'multi'` for multi-label classification (default is `'single'`)
  - `task_description`: Brief explanation of the classification task (50 words max) to improve accuracy

**Return Value**
Returns a JSON object containing a `"labels"` array.
- Single-label mode: `{"labels": ["best_match"]}`
- Multi-label mode: `{"labels": ["match_1", "match_2"]}`

**Example**
```sql
-- Example 1: Simple Single-Label Classification
SELECT AI_CLASSIFY(
    'My internet is not working',
    ['technical_issue', 'billing', 'general_inquiry']
);
-- Returns: {"labels": ["technical_issue"]}

-- Example 2: Multi-Label Classification
SELECT AI_CLASSIFY(
    'I love traveling and cooking.',
    ['travel', 'cooking', 'gaming'],
    {'output_mode': 'multi'}
);
-- Returns: {"labels": ["travel", "cooking"]}

-- Example 3: Using Label Descriptions for Better Accuracy
SELECT AI_CLASSIFY(
    'Customer threatening to cancel unless resolved today',
    [
        {'label': 'urgent', 'description': 'needs immediate attention within 24 hours'},
        {'label': 'normal', 'description': 'standard priority request'},
        {'label': 'low', 'description': 'can be handled when convenient'}
        ]
);
-- Returns: {"labels": ["urgent"]}

-- Example 4: With Task Description
SELECT AI_CLASSIFY(
    'The package arrived damaged',
    ['product_quality', 'shipping_issue', 'customer_service'],
    {'task_description': 'Classify customer complaints by root cause department'}
);
-- Returns: {"labels": ["shipping_issue"]}
```

---

### AI_SENTIMENT

**Syntax**
`AI_SENTIMENT(<text> [, <categories>])`

**Description**
Evaluates the emotional tone of text. It can provide a general sentiment score for the whole text or break it down by specific aspects (categories) you define.

**Parameters**
- `text`: The text string to analyze.
- `categories` (Optional): An array of strings representing specific aspects to analyze (e.g., `['Food', 'Service']`).
  - Maximum 10 categories
  - Each category can be up to 30 characters long
  - If omitted, only the overall sentiment is returned

**Return Value**
Returns a JSON object with a `"categories"` array. Each category includes:
- `name`: The category name (always includes `"overall"` for global sentiment)
- `sentiment`: One of `positive`, `negative`, `neutral`, `mixed`, `unknown`

**Example**
```sql
-- Example 1: Overall sentiment only (no categories specified)
SELECT AI_SENTIMENT('The pizza was great!');
-- Returns:
-- {
--   "categories": [
--     {"name": "overall", "sentiment": "positive"}
--   ]
-- }

-- Example 2: Sentiment for specific aspects
SELECT AI_SENTIMENT(
    'The pizza was great but the delivery was late.',
    ['Food', 'Delivery']
);
-- Returns:
-- {
--   "categories": [
--     {"name": "overall", "sentiment": "mixed"},
--     {"name": "Food", "sentiment": "positive"},
--     {"name": "Delivery", "sentiment": "negative"}
--   ]
-- }
```

---

### AI_EXTRACT

**Syntax**
`AI_EXTRACT(<text>, <responseFormat>)`

**Description**
Extracts specific, structured facts from unstructured text. You define the schema by mapping output fields to natural language questions or descriptions.

**Parameters**
- `text`: The text string to extract information from (use named parameter: `text => '...'`).
- `responseFormat`: Defines what to extract. Supports two formats:
  - **Object format** (with labels): `{'name': 'What is the person name?', 'city': 'What is the city?'}`
  - **Array format** (auto-labeled): `['What is the person name?', 'What is the city?']`
  - Can use questions ("What is...?") or descriptions ("First and last name", "City, street, ZIP")

**Limits**
- Maximum 100 extraction questions per call
- Maximum output length: 512 tokens per question

**Return Value**
Returns a JSON object with structure:
```json
{
  "error": null,
  "response": {
    "field1": "extracted_value1",
    "field2": "extracted_value2"
  }
}
```

**Example**
```sql
-- Example 1: Object format with questions
SELECT AI_EXTRACT(
    text => 'John Doe lives in New York and works for Snowflake.',
    responseFormat => {
        'name': 'What is the person name?',
        'city': 'What is the city?',
        'company': 'What company does the person work for?'
    }
);
-- Returns: {"error": null, "response": {"name": "John Doe", "city": "New York", "company": "Snowflake"}}

-- Example 2: Array format (simpler syntax)
SELECT AI_EXTRACT(
    text => 'John Doe lives in New York.',
    responseFormat => [
        'What is the first name?',
        'What is the last name?',
        'Where does the person live?'
    ]
);
-- Returns: {"error": null, "response": ["John", "Doe", "New York"]}

-- Example 3: Using descriptions instead of questions
SELECT AI_EXTRACT(
    text => 'Contact: John Doe, 123 Main St, New York, 10001',
    responseFormat => {
        'name': 'First and last name',
        'address': 'Street address',
        'city': 'City name',
        'zip': 'ZIP code'
    }
);
-- Returns: {"error": null, "response": {"name": "John Doe", "address": "123 Main St", "city": "New York", "zip": "10001"}}
```

---

### AI_FILTER

**Syntax**
`AI_FILTER(<input>)`

**Description**
A logical function that returns **TRUE** or **FALSE** based on whether the input meets a natural language condition. Best used in `WHERE` clauses for semantic filtering without writing complex pattern matching logic.

**Parameters**
- `input`: A natural language statement or question describing the criteria. Can be:
  - A simple string constant: `AI_FILTER('Is Canada in North America?')`
  - Combined with columns using `CONCAT()`: `CONCAT('statement: ', column)`
  - Formatted using `PROMPT()`: `PROMPT('statement: {0}', column)`

**Usage Tips**
- Provide detailed instructions rather than vague statements (e.g., "In the following review, the customer is satisfied" is better than "satisfied")
- Consider phrasing as a question (e.g., "Does the customer sound satisfied?")
- Ensure columns don't contain NULL values for optimal performance

**Return Value**
Returns a `BOOLEAN` (`TRUE` or `FALSE`).

**Example**
```sql
-- Example 1: Using PROMPT()
SELECT * FROM reviews
WHERE AI_FILTER(PROMPT('The reviewer enjoyed the restaurant: {0}', review_text));
-- Returns rows where review_text indicates positive experience

-- Example 2: Using CONCAT()
SELECT * FROM reviews
WHERE AI_FILTER(CONCAT('The customer is satisfied with the service: ', review_text));
-- Returns rows where review_text indicates satisfaction

-- Example 3: Simple boolean evaluation
SELECT AI_FILTER('Is Canada in North America?') AS result;
-- Returns: TRUE

-- Example 4: Cross-table filtering with multiple columns
SELECT country, region
FROM countries CROSS JOIN regions
WHERE AI_FILTER(PROMPT('{0} is in {1}', country, region));
-- Returns:
-- | COUNTRY     | REGION |
-- |-------------|--------|
-- | Switzerland | Europe |
-- | Korea       | Asia   |
```

---

### AI_SIMILARITY

**Syntax**
`AI_SIMILARITY(<input1>, <input2>)`

**Description**
Calculates the semantic similarity between two text inputs using vector embeddings. It measures conceptual closeness rather than keyword overlap.

**Parameters**
- `input1`: Text string to compare.
- `input2`: Text string to compare against.

**Return Value**
Returns a `FLOAT` between -1.0 and 1.0 (1.0 being identical/highly similar).

**Example**
```sql
-- Find reviews semantically similar to a specific statement
SELECT review_text, AI_SIMILARITY(review_text, 'The battery drains too fast') as similarity_score
FROM product_reviews
ORDER BY AI_SIMILARITY(review_text, 'The battery drains too fast') DESC
LIMIT 3;
-- Returns:
-- | REVIEW_TEXT                                  | SIMILARITY_SCORE |
-- |----------------------------------------------|------------------|
-- | The battery life is terrible                 | 0.89             |
-- | Power drains way too quickly on this device  | 0.85             |
-- | Battery doesn't last long enough             | 0.82             |
```

---

### AI_AGG

**Syntax**
`AI_AGG(<expr>, <instruction>)`

**Description**
An aggregate function that processes a group of text rows to generate a single summary or analysis based on your instruction. Unlike standard text functions, AI_AGG supports datasets larger than the model's context window, making it suitable for aggregating large volumes of text.

**Parameters**
- `expr`: The text column or expression to aggregate. Can use `CONCAT()` or `||` to combine multiple columns.
- `instruction`: A natural language string specifying how to aggregate the data.

**Usage Tips**
- Use **declarative statements** instead of questions (e.g., "Summarize the reviews" not "Can you summarize?")
- **Describe the data** in your instruction (e.g., "Summarize the phone call transcripts" not just "summarize")
- **Describe the use case** for better results (e.g., "Find the most positive review to highlight on our website")
- Break complex instructions into steps for clarity

**Return Value**
Returns a single string result per group.

**Example**
```sql
-- Example 1: Simple aggregation with GROUP BY
SELECT
    product_id,
    AI_AGG(review_text, 'Summarize the product reviews for potential consumers') as summary
FROM reviews
GROUP BY product_id;
-- Returns table:
-- | PRODUCT_ID | SUMMARY                                                                                |
-- |------------|----------------------------------------------------------------------------------------|
-- | 1          | Reviews are mixed. Most customers praised the battery life and camera quality,        |
-- |            | but some complained about slow charging and occasional screen glitches.               |
-- | 2          | Overwhelmingly positive feedback. Users love the design and performance.              |

-- Example 2: Combining multiple columns
SELECT
    restaurant_id,
    AI_AGG(
        'Menu Item: ' || menu_item || '\nReview: ' || review_text,
        'Summarize the restaurant reviews, highlighting menu items mentioned'
    ) as summary
FROM restaurant_reviews
GROUP BY restaurant_id;
-- Returns table:
-- | RESTAURANT_ID | SUMMARY                                                                       |
-- |---------------|-------------------------------------------------------------------------------|
-- | 1             | The pizza receives high praise with customers calling it 'excellent'.        |
-- |               | Burgers and pancakes get mixed reviews, with some finding them mediocre.     |
-- | 2             | Terrible quality ingredients across all menu items. Multiple customers advise |
-- |               | avoiding this restaurant.                                                     |

-- Example 3: Specific extraction task (more deterministic)
SELECT
    product_id,
    AI_AGG(review_text, 'Identify the most positive review and translate it to French as a single sentence') as best_review
FROM reviews
GROUP BY product_id;
-- Returns table:
-- | PRODUCT_ID | BEST_REVIEW                                                      |
-- |------------|------------------------------------------------------------------|
-- | 1          | Ce produit est absolument incroyable et a dépassé mes attentes. |
-- | 2          | Qualité exceptionnelle, je le recommande vivement.              |

-- Example 4: Aggregating all rows (no GROUP BY)
SELECT AI_AGG(
    feedback,
    'List the top 3 most common complaints mentioned by customers'
) as common_complaints
FROM customer_feedback;
-- Returns single string:
-- "1. Slow delivery times (mentioned in 45% of complaints)
--  2. Poor customer service responsiveness (32%)
--  3. Product quality issues (28%)"
```
</ai_functions_reference>"""


MODIFICATION_APPROACHES = """<modification_approaches>
**Inspiration for AI Integration**

You have substantial flexibility in how you incorporate AI functions into SQL queries. Approach this task with creativity. While determinism and correctness are non-negotiable, the way you integrate AI functions can be imaginative. Look for non-obvious opportunities where semantic understanding adds genuine analytical value. Don't limit yourself to straightforward replacements, consider combinations, nested operations, or multi-stage transformations that unlock insights not achievable with traditional SQL alone.

These concepts below are starting points to spark your creativity, not rigid rules. You should combine these ideas or invent new ways to evolve the analytical intent. Your goal is to ask: "How can I upgrade this request to leverage semantic understanding?"

**Concept 1: From Keyword Matching to Semantic Understanding**
When you see an original query relying on simple `LIKE` matching or standard equality filters, consider whether the user's underlying intent is actually about *meaning*.
* The Opportunity: Instead of filtering for rows containing the string "slow", evolve the instruction to filter for a semantic condition like "complaints about performance being slow." This naturally introduces `AI_FILTER` (semantic boolean condition) or `AI_SIMILARITY` (rank + LIMIT/threshold), moving from syntax matching to concept matching. Use `AI_CLASSIFY` only when you truly need stable discrete buckets for grouping or stratification.

**Concept 2: From Arbitrary Sorting to Relevance Ranking**
When you encounter a query that retrieves a list of records but sorts them arbitrarily (e.g., by Date or ID), consider whether the user would prefer to see the *most relevant* results first.
* The Opportunity: You can refine the instruction to request the "top N most relevant results" regarding a specific topic. This naturally creates a need for `AI_SIMILARITY` in the `ORDER BY` clause, often transforming a flat list into a prioritized insights list.

**Concept 3: From Metadata Grouping to Content Synthesis**
When the original query groups data by standard columns (like Country or Date), consider whether the analysis would be richer if grouped by insights hidden *within* the text.
* The Opportunity: You could formulate a new layer that asks to "identify complaints by specific defect type" or "group feedback by extracted product names." This naturally requires using `AI_EXTRACT` or `AI_CLASSIFY` to structure the unstructured text before aggregation, creating dimensions that didn't exist in the original schema.

**Concept 4: ... (Feel free to think more)

**Synthesis**
The most powerful modifications often layer multiple concepts and combine different AI functions where it makes analytical sense. Feel free to blend approaches to create the most valuable analytical request possible.

**On Function Selection**
Choose the AI function that most directly matches the analytical intent, and prefer the simplest function that accomplishes the semantic goal.

- If the goal is "filter by meaning" (replace brittle LIKE/keyword rules): prefer `AI_FILTER` (boolean semantic condition) or `AI_SIMILARITY` (rank + LIMIT / threshold).
- If the goal is "rank by relevance": prefer `AI_SIMILARITY` in `ORDER BY` with an explicit LIMIT/threshold.
- If the goal is "extract structured fields from text": prefer `AI_EXTRACT` with an explicit extraction question and format.
- If the goal is "summarize/aggregate many rows into a short insight": prefer `AI_AGG` with a fully specified aggregation instruction.
- Use `AI_CLASSIFY` when discrete bucketing is central to the analysis (grouping, filtering, or stratification).

You may combine functions when the logic naturally chains (e.g., similarity → filter → aggregate), but do not add AI functions as an afterthought.

**AI_CLASSIFY Companion Rule**
If you use AI_CLASSIFY, you must also incorporate at least one other AI function (AI_SIMILARITY, AI_FILTER, AI_AGG, or AI_EXTRACT) into the query. This ensures benchmark diversity and prevents over-reliance on classification alone.

**Structural Requirement**
AI functions must influence the query logic, they should be used in WHERE, GROUP BY, ORDER BY, HAVING, or QUALIFY clauses. A classification or other AI result that only appears in SELECT without affecting row selection, grouping, or ordering is superficial and does not demonstrate meaningful AI integration.

**AI Necessity Rule**
Do not use AI functions for logic that can be handled by simple SQL. If a classification is based purely on numeric ranges (e.g., "0 days = Immediate, 1-3 days = Quick") or exact string matches (e.g., "contains 'LLC' = Corporation"), use CASE WHEN instead. AI functions are for genuine semantic understanding of natural language text, not for replacing conditional logic.
</modification_approaches>"""



INTEGRATION_EXAMPLES = """<integration_examples>
These examples illustrate common pitfalls and good practices. They are meant to provide direction and contrast, not templates to follow. Be creative in your approach, the best integrations often look nothing like these examples but share the same underlying principles.

Your goal is to embed AI parameters naturally into the flow of the original question, making the instruction read as a coherent analytical question rather than a procedure or mechanical command.

NOTE: The examples below are intentionally simplified. Real-world queries will be much more complex, but the same principles may apply.

---

Example 1: Avoiding Mechanical Phrasing

The instruction should embody Organic Integration, AI logic woven seamlessly into the question, not bolted on as a separate step or mechanical command. This applies to all AI functions.

Original: "In which year did the assignee with the most applications in patent category 'A61' file the most?"

BAD: "In which year did the top assignee in 'A61' file the most? Additionally, classify them into University, Corporation, or Government."
- Critique: "Additionally" signals a separate post-processing step, violating Organic Integration.

BAD: "First, find the top assignee in 'A61'. Then classify them into ['University', 'Corporation', 'Government']. Finally, return the assignee name, classification, and year."
- Critique: Step-by-step instructions read like a procedure, not an analytical question.

BAD: "Classify assignees into ['University', 'Corporation', 'Government'] for 'A61'. Return columns: assignee_name, classification, year, application_count."
- Critique: "Return columns: X, Y, Z" is a database command. Per Minimal Output, let the question structure imply what to return.

GOOD: "In which year did the top 'University' assignee, classified into ['University', 'Corporation', 'Government', 'Other'] based on organization name, file the most applications in category 'A61'?"
- Why it works: Classification is embedded in the subject ("the top 'University' assignee"), the input field is specified ("based on organization name"), and the complete category list is given. The question naturally implies returning the year.

---

Example 2: Avoiding Direct Score Output

Similarity scores are high-precision floats (e.g., 0.3014192...) that complicate benchmark validation. Use scores for ordering or filtering, not as output columns.

Original: "What are the top 10 reviews that mention battery problems?"

BAD: "What are the top 10 reviews most similar to 'battery drains quickly'? Display each review with its similarity score."
- Critique: Outputting raw float scores makes validation difficult. Per Minimal Output, only return what the question asks for.

GOOD: "What are the top 10 reviews most similar to 'battery drains quickly'?"
- Why it works: Score used only for ranking (ORDER BY), not displayed. The question asks "what are the reviews," returning only review content.

---

Example 3: Avoiding Undeterministic Instructions

Per Specification Determinism, another engineer reading your instruction must write exactly the same AI SQL code. Vague parameters, missing bounds, ambiguous formats, and invalid enums all break this. Here are examples across different AI functions:

(a) Missing bounds or vague reference text:

Original: "What are the top 10 reviews that mention battery problems?"

BAD: "What are the reviews similar to battery issues?"
- Critique: No bound (threshold or limit) means unbounded results. Reference text lacks quotes, engineers might interpret it as 'battery issues', 'battery problems', or something else.

GOOD: "What are the top 20 reviews with similarity above 0.6 to 'battery drains quickly'?"
- Why it works: Both threshold (> 0.6) and limit (top 20) ensure deterministic results. Reference text is quoted exactly.

(b) Ambiguous aspects or invalid enums:

Original: "Which restaurant reviews have negative feedback about food quality?"

BAD: "Which reviews have negative sentiment for Food and Service aspects?"
- Critique: Is this one aspect 'Food and Service' or two? Different engineers would write different SQL.

BAD: "Which reviews show that customers are unhappy with the food?"
- Critique: 'unhappy' is not a valid enum. Valid values: 'positive', 'negative', 'neutral', 'mixed', 'unknown'.

GOOD: "Which reviews have 'negative' sentiment for the 'Food' aspect?"
- Why it works: Quoted aspect ('Food') is unambiguous. Uses exact enum value ('negative').

(c) Vague condition phrases or missing input format:

Original: "Which product reviews indicate the customer would buy again?"

BAD: "Which reviews are from satisfied customers who would repurchase?"
- Critique: "satisfied" and "repurchase" are vague, different engineers would use different condition phrases.

GOOD: "Which reviews satisfy the condition 'The customer explicitly states they would purchase this product again' when concatenated as 'Review: {review_text}'?"
- Why it works: Exact condition phrase quoted, and CONCAT format explicitly specified.

(d) Unspecified extraction questions:

Original: "What is the effective date for each contract?"

BAD: "Extract the effective date from each contract."
- Critique: What extraction question? 'Effective date?', 'What is the start date?', 'When does it begin?', each yields different results.

GOOD: "What is the effective date for each contract, using the extraction question 'What is the contract effective date? Format: YYYY-MM-DD'?"
- Why it works: Exact extraction question is quoted, including expected format.

(e) Vague output format for aggregation:

Original: "List all customer feedback comments for each product category."

BAD: "For each category, aggregate feedback using the instruction 'Summarize the main issues mentioned by customers in one concise sentence'."
- Critique: "in one concise sentence" does not specify an explicit output structure. The format of the result is left to the model's interpretation.

GOOD: "For each category, aggregate feedback using the instruction 'List the top 3 issues, formatted as: Issue1; Issue2; Issue3'."
- Why it works: Explicit format specification ensures a predictable, compact structure like "slow delivery; poor packaging; wrong items".

---

Example 4: Encouraging Multiple AI Functions

A single AI function is valid and often sufficient. However, combining functions can create richer benchmarks when the analytical logic naturally supports it. The key is that multiple functions should be logically chained, not artificially appended. Prioritize executability over complexity.

The examples below show just two of many possible combinations, do not limit yourself to these specific patterns. Think about what combination best fits your analytical question.

Original: "What are the main complaints in customer reviews about our products?"

Simple version (single function):
"What are the top 20 reviews most similar to 'poor quality and disappointed with purchase'?"
- Uses similarity to find complaint-like reviews. Straightforward and effective.

Richer version (multiple functions):
"What are the top 20 reviews most similar to 'poor quality and disappointed with purchase', but only those where overall sentiment is 'negative'?"
- Similarity ranking identifies complaint-like content, then sentiment filtering ensures they are genuinely negative. The two functions work together logically, similarity finds candidates, sentiment validates them.

Another example of natural combination:
Original: "Categorize and summarize feedback by product type."

"For each product, classified into ['Electronics', 'Apparel', 'Home', 'Other'] based on product name, aggregate its reviews using the instruction 'Return the main praise and main complaint, formatted as: Praise: [text]; Complaint: [text]'."
- Classification groups products based on their names, then aggregation summarizes each group. The classification directly determines which reviews get aggregated together.

Important: If a multi-function approach fails after several attempts, fall back to a simpler working version. A working single-function solution is always better than an incomplete multi-function one.
</integration_examples>"""