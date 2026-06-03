-- cleanup_forecast_months_duplicates_sqlite.sql
-- Removes duplicate forecastmonthsmodel rows per UploadedFile,
-- keeping only the record with the latest CreatedDateTime.
--
-- Run this once before deploying the upsert logic to clean up
-- any pre-existing duplicates created by the old insert-only behaviour.
--
-- Compatible with: SQLite 3.25+ (supports window functions).

DELETE FROM forecastmonthsmodel
WHERE id NOT IN (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY UploadedFile
                ORDER BY CreatedDateTime DESC
            ) AS rn
        FROM forecastmonthsmodel
    ) ranked
    WHERE rn = 1
);
