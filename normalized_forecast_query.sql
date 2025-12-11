-- This query joins ForecastModel with ForecastMonthsModel and "unpivots" the
-- monthly forecast data into a normalized, long-format table.

SELECT
    -- Identifier columns from ForecastModel
    fm.Centene_Capacity_Plan_Main_LOB,
    fm.Centene_Capacity_Plan_State,
    fm.Centene_Capacity_Plan_Case_Type,
    fm.Centene_Capacity_Plan_Call_Type_ID,
    fm.Centene_Capacity_Plan_Target_CPH,

    -- Audit and context columns
    fm.UploadedFile,
    fm.Month AS UploadMonth,
    fm.Year AS UploadYear,

    -- Unpivoted columns from the CROSS APPLY operation
    up.ForecastMonth,
    up.Client_Forecast,
    up.FTE_Required,
    up.FTE_Avail,
    up.Capacity

FROM
    ForecastModel AS fm
-- Join with ForecastMonthsModel to get the actual names of the forecast months
JOIN
    ForecastMonthsModel AS fmm ON fm.UploadedFile = fmm.UploadedFile

-- Unpivot the 6 sets of monthly metric columns into individual rows
CROSS APPLY (
    VALUES
        (fmm.Month1, fm.Client_Forecast_Month1, fm.FTE_Required_Month1, fm.FTE_Avail_Month1, fm.Capacity_Month1),
        (fmm.Month2, fm.Client_Forecast_Month2, fm.FTE_Required_Month2, fm.FTE_Avail_Month2, fm.Capacity_Month2),
        (fmm.Month3, fm.Client_Forecast_Month3, fm.FTE_Required_Month3, fm.FTE_Avail_Month3, fm.Capacity_Month3),
        (fmm.Month4, fm.Client_Forecast_Month4, fm.FTE_Required_Month4, fm.FTE_Avail_Month4, fm.Capacity_Month4),
        (fmm.Month5, fm.Client_Forecast_Month5, fm.FTE_Required_Month5, fm.FTE_Avail_Month5, fm.Capacity_Month5),
        (fmm.Month6, fm.Client_Forecast_Month6, fm.FTE_Required_Month6, fm.FTE_Avail_Month6, fm.Capacity_Month6)
) AS up(ForecastMonth, Client_Forecast, FTE_Required, FTE_Avail, Capacity);
