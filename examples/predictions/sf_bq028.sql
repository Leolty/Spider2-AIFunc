WITH latest_versions AS (
    SELECT "Name", "Version"
    FROM DEPS_DEV_V1.DEPS_DEV_V1.PACKAGEVERSIONS
    WHERE "System" = 'NPM'
      AND "VersionInfo":"IsRelease"::BOOLEAN = TRUE
      AND "Name" NOT LIKE '%>%'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY "Name" ORDER BY "VersionInfo":"Ordinal"::INT DESC) = 1
),
pkg_with_stars AS (
    SELECT lv."Name", lv."Version", MAX(p."StarsCount") AS "StarsCount"
    FROM latest_versions lv
    JOIN DEPS_DEV_V1.DEPS_DEV_V1.PACKAGEVERSIONTOPROJECT pvp
      ON lv."Name" = pvp."Name" AND lv."Version" = pvp."Version" AND pvp."System" = 'NPM'
    JOIN DEPS_DEV_V1.DEPS_DEV_V1.PROJECTS p
      ON pvp."ProjectName" = p."Name" AND pvp."ProjectType" = p."Type"
    GROUP BY lv."Name", lv."Version"
    ORDER BY "StarsCount" DESC
    LIMIT 200
),
similarity_filtered AS (
    SELECT "Name", "Version", "StarsCount"
    FROM pkg_with_stars
    WHERE AI_SIMILARITY("Name", 'frontend UI component library framework') > 0.3
),
classified AS (
    SELECT "Name", "Version", "StarsCount",
        AI_CLASSIFY("Name", ['UI Framework', 'CSS Framework', 'Utility Library', 'Data Visualization', 'Build Tool', 'Backend Framework', 'Other']):labels[0]::STRING AS "Category"
    FROM similarity_filtered
)
SELECT "Name", "Version", "Category"
FROM classified
WHERE "Category" IN ('UI Framework', 'CSS Framework')
ORDER BY "StarsCount" DESC, "Name" ASC
LIMIT 8
