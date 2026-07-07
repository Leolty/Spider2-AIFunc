WITH TopGithubProjects AS (
    SELECT
        "Name" AS "ProjectName",
        "StarsCount"
    FROM "DEPS_DEV_V1"."DEPS_DEV_V1"."PROJECTS"
    WHERE "Type" = 'GITHUB' AND "StarsCount" IS NOT NULL
    ORDER BY "StarsCount" DESC
    LIMIT 2000
),
DeduplicatedPackages AS (
    SELECT
        pvp."Name" AS "PackageName",
        tgp."StarsCount"
    FROM TopGithubProjects AS tgp
    JOIN "DEPS_DEV_V1"."DEPS_DEV_V1"."PACKAGEVERSIONTOPROJECT" AS pvp
        ON tgp."ProjectName" = pvp."ProjectName"
    WHERE
        pvp."ProjectType" = 'GITHUB'
        AND pvp."System" = 'NPM'
        AND pvp."Name" NOT LIKE '%>%'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY "PackageName" ORDER BY "StarsCount" DESC) = 1
),
LatestRelevantNPMReleases AS (
    SELECT
        "Name",
        "Version"
    FROM "DEPS_DEV_V1"."DEPS_DEV_V1"."PACKAGEVERSIONS"
    WHERE
        "System" = 'NPM'
        AND "VersionInfo":IsRelease = TRUE
        AND "Name" IN (SELECT "PackageName" FROM DeduplicatedPackages)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY "Name" ORDER BY "VersionInfo":Ordinal DESC) = 1
),
PackageDetails AS (
    SELECT
        dp."PackageName",
        lrnr."Version",
        dp."StarsCount"
    FROM DeduplicatedPackages AS dp
    JOIN LatestRelevantNPMReleases AS lrnr
        ON dp."PackageName" = lrnr."Name"
),
ClassifiedPackages AS (
    SELECT
        "PackageName",
        "Version",
        "StarsCount",
        AI_CLASSIFY("PackageName", ['UI Framework', 'CSS Framework', 'Utility Library', 'Data Visualization', 'Build Tool', 'Backend Framework', 'Other']):labels[0]::STRING AS category
    FROM PackageDetails
    WHERE AI_SIMILARITY("PackageName", 'frontend UI component library framework') > 0.3
)
SELECT
    "PackageName",
    "Version",
    category
FROM ClassifiedPackages
WHERE category IN ('UI Framework', 'CSS Framework')
ORDER BY "StarsCount" DESC, "PackageName" ASC
LIMIT 8
