WITH education_articles AS (
    SELECT
        "category",
        AI_SENTIMENT(LEFT("body", 2000)):categories[0].sentiment::STRING AS sentiment
    FROM BBC.BBC_NEWS.FULLTEXT
    WHERE LOWER("body") LIKE '%education%'
)
SELECT
    "category",
    sentiment,
    COUNT(*) AS article_count
FROM education_articles
WHERE sentiment IN ('positive', 'negative', 'neutral', 'mixed')
GROUP BY "category", sentiment
ORDER BY "category" ASC, sentiment ASC;
