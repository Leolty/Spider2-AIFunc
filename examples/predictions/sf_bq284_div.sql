SELECT 
    "category",
    AI_SENTIMENT(LEFT("body", 2000)):categories[0]:sentiment::STRING AS sentiment,
    COUNT(*) AS article_count
FROM BBC.BBC_NEWS.FULLTEXT
WHERE LOWER("body") LIKE '%education%'
GROUP BY "category", sentiment
ORDER BY "category" ASC, sentiment ASC
