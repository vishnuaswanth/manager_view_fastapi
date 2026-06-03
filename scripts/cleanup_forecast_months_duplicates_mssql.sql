-- cleanup_forecast_months_duplicates_mssql.sql
-- Removes duplicate forecastmonthsmodel rows per UploadedFile,
-- keeping only the record with the latest CreatedDateTime.
--
-- Run this once before deploying the upsert logic to clean up
-- any pre-existing duplicates created by the old insert-only behaviour.
--
-- Compatible with: Microsoft SQL Server 2008 R2+.

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY UploadedFile
            ORDER BY CreatedDateTime DESC
        ) AS rn
    FROM forecastmonthsmodel
)
DELETE FROM forecastmonthsmodel
WHERE id IN (
    SELECT id FROM ranked WHERE rn > 1
);
